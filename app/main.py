from fastapi import FastAPI, Request, Query, HTTPException, UploadFile, File, APIRouter, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
import time, asyncio, zipfile, json, logging, traceback
from io import BytesIO
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta, timezone
from sqlalchemy import update, select


# Import Spotify helper functions
from app.oauth import OAuthSettings, SpotifyOAuth, SpotifyHandler, SpotifyUser
from app.spotify_api import SpotifyClient
from app.database import get_db_connection, AsyncSessionLocal
from app.helpers import MusicDataService, UserMusicUpdater, TokenRefresh
from app.db import User

# Function to fetch user data from Spotify
import httpx


settings = OAuthSettings()
spotify_oauth = SpotifyOAuth(settings)

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start scheduler ONCE
    if not scheduler.running:
        scheduler.add_job(refresh_tokens_periodically, 'interval', minutes=5)
        scheduler.start()
    yield
    # Stop scheduler on shutdown
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
router = APIRouter()

async def refresh_tokens_periodically():
    print("starting token refresh job")
    async with AsyncSessionLocal() as db:
        print("[Scheduler] Token refresh job started.")
        data_service = TokenRefresh(db)
        users = await data_service.get_all_users_from_db()

        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=5)

        for user in users:
            try:
                expires_at = user.token_expires
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)

                print(f"[{now}] Checking user {user.user_id} token expiry: {expires_at} (UTC)")

                if expires_at <= now + buffer:
                    print(f"[{now}] Token for user {user.user_id} is expiring or expired. Refreshing...")
                    new_token = await spotify_oauth.refresh_access_token(user.refresh_token)
                    print("New token data:", new_token)

                    if new_token:
                        await data_service.update_user_token(
                            user_id=user.user_id,
                            access_token=new_token["access_token"],
                            refresh_token=new_token.get("refresh_token", user.refresh_token),
                            token_expires=datetime.fromtimestamp(new_token["expires_at"], tz=timezone.utc)
                        )
                    else:
                        print(f"Failed to refresh token for user {user.user_id}.")
                else:
                    print(f"[{now}] Token for user {user.user_id} is still valid.")
            except Exception as e:
                print(f"Error refreshing token for user {user.user_id}: {e}")

# ✅ Session Middleware (Make sure secret_key is correctly set)
app.add_middleware(SessionMiddleware, secret_key="your_super_secret_key", session_cookie="spotify_session")

# ✅ Setup Jinja2 Templates
templates = Jinja2Templates(directory="app/templates") 

# ✅ Serve static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ---------------------------------------
# 🎵 1️⃣ Spotify Login & Auth Flow
# ---------------------------------------

@app.get("/")
async def root(request: Request):
    # Get the Spotify token from the session (None if not logged in)
    access_token = request.session.get("spotify_token")
    client_data = SpotifyClient(access_token)

    # Default values in case the user is not logged in
    user_image, user_name = None, "Guest"

    # If the user is logged in, fetch user profile data
    if access_token:
        db = get_db_connection()
        cursor = db.cursor()

        # Get the user profile from Spotify
        user_profile = await client_data.get_spotify_user_profile()
        spotify_user = SpotifyUser(access_token)
        user_data = await spotify_user.store_user_info_to_database(user_profile, db)
        user_id = user_data["id"]

        # Fetch user info from the database (image and name)
        cursor.execute("SELECT images, display_name FROM users WHERE id = %s;", (user_id,))
        user_info = cursor.fetchone()  # Fetch only once

        # Handle user information safely
        if user_info:
            user_image, user_name = user_info  # Unpack values
        else:
            user_image, user_name = None, "Unknown User"  # Default values if data is missing

    # Return the index page with user data
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user_image": user_image,
        "user_name": user_name
    })

@app.get("/layout")
async def layout_page(request: Request, user_data: dict = Depends(SpotifyHandler.get_current_user)):
    db = await get_db_connection()  # Get the async connection

    user_id = user_data.get("user_id")
    print(f"User ID from session: {user_id}")  

    user_info = await db.fetchrow("SELECT image_url, display_name FROM users WHERE user_id = $1;", user_id)

    await db.close()  # Properly close the async connection

    if user_info:
        user_image, user_name = user_info["image_url"], user_info["display_name"]
    else:
        user_image, user_name = None, "Unknown User"

    return templates.TemplateResponse("layout.html", context={
        "request": request,
        "user_id": user_id,
        "user_image": user_image,
        "user_name": user_name
    })


@app.get("/login-page")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/login")
def login(request: Request):
    return RedirectResponse(spotify_oauth.get_spotify_login_url(request))

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.get("/callback")
async def callback(request: Request):
    state = request.query_params.get("state")
    stored_state = request.session.get("spotify_auth_state")

    if not state or state != stored_state:
        raise HTTPException(status_code=400, detail="State mismatch. Possible CSRF attack.")

    try:
        spotify_handler = SpotifyHandler(settings, spotify_oauth)
        result = await spotify_handler.handle_spotify_callback(request)

        request.session["spotify_token"] = result["access_token"]
        request.session["user_id"] = result["user_profile"]["id"]

        return RedirectResponse(url="/dashboard")

    except Exception as e:
        print(f"Callback error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)





async def get_spotify_user_profile(token):
    url = "https://api.spotify.com/v1/me"
    headers = {"Authorization": f"Bearer {token}"}

    while True:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)

            if response.status_code == 200:
                return response.json()  # ✅ Success

            elif response.status_code == 429:  # 🚨 Too Many Requests
                retry_after = int(response.headers.get("Retry-After", 5))  # Default wait: 5 sec
                print(f"⚠️ 429 Too Many Requests. Retrying after {retry_after} seconds...")
                time.sleep(retry_after)  # ⏳ Wait before retrying
                continue  # Retry the request

            else:
                print(f"❌ Error fetching user profile: {response.status_code} - {response.text}")
                return None  # 🚨 Other errors, return None



# ---------------------------------------
# 🎵 2️⃣ Fetch & Display Spotify Data
# ---------------------------------------


@app.get("/dashboard")
async def dashboard(request: Request, limit: int = 1000, offset: int = 0, user_data: dict = Depends(SpotifyHandler.get_current_user)):
    db = None
    try:

        token = user_data["token"]  # Extract token if needed
        user_id = user_data["user_id"]  # Extract user_id if needed
        print(f"User ID from session: {user_id}")

        db = await get_db_connection()
        time_range = request.query_params.get('time_range', 'medium_term')

        updater = UserMusicUpdater(db, user_id, token)

        await asyncio.gather(
            updater.update_data_if_needed("top_artists", time_range),
            updater.update_data_if_needed("top_tracks", time_range),
            updater.update_data_if_needed("recent_tracks", time_range)
        )

        user_service = MusicDataService(user_id, db)

        user_info = await user_service.get_user_info()
        top_artist_list = await user_service.get_top_artists_db(time_range)
        top_tracks_list = await user_service.get_top_tracks_db(time_range)
        track_play_counts = await user_service.get_track_play_counts()
        daily_play_count = await user_service.get_daily_play_counts()
        total_play_count = await user_service.get_total_play_count()
        total_play_today = await user_service.get_total_play_today()
        daily_listening_time = await user_service.get_daily_listening_time()
        total_listened_minutes, total_listened_hours = await user_service.get_total_listening_time()
        top_genres = await user_service.get_top_genres()
        records_by_time = await user_service.complete_listening_history(limit, offset)


        #TESTING 
        print("TESTING:")
        days_listened = await user_service.get_consecutive_days_listened() #passed
        print(f"Consecutive days listened: {days_listened}")
        biggest_streak_one_song = await user_service.get_most_listened_song_streak() #passed
        print(f"Biggest streak for one song: {biggest_streak_one_song}")
        streak_inbetween_song = await user_service.get_streak_of_song_played_inbetween() #passed
        print(f"Streak of song played inbetween: {streak_inbetween_song}")
        average_song_popularity = await user_service.get_average_popularity() #passed
        print(f"Average song popularity: {average_song_popularity}")
        average_album_release_date = await user_service.get_average_release_date() #passed
        print(f"Average album release date: {average_album_release_date}")

        # top artists and top tracks from local database per user
        async with AsyncSessionLocal() as session:
            stats = MusicDataService(user_id, session)

            top_tracks = await stats.get_top_tracks(limit=50)
            print("Top Tracks:")
            for i, track in enumerate(top_tracks, start=1):
                print(f"{i}. {track['name']} - {track['total_streams']} streams")

            top_artists = await stats.get_top_artists(limit=50)
            print("Top Artists:")
            for i, artist in enumerate(top_artists, start=1):
                print(f"{i}. {artist['name']} - {artist['total_streams']} streams")

        # Fetch user to artist stats // artist, number of streams, distinct tracks listened, total duration 
        user_to_artist = await user_service.get_user_artist_stats(user_id)
        print("User to Artist Stats:")
        for row in user_to_artist:
            artist_id = row["artist_id"]
            artist_name = row["artist_name"]
            total_duration = row["total_duration_ms"]
            total_streams = row["total_streams"]
            distinct_tracks_listened = row["distinct_tracks_listened"]
            total_seconds = total_duration // 1000 if total_duration else 0
            formatted_duration = str(timedelta(seconds=total_seconds))
            print(f"Artist ID: {artist_id}, Artist Name: {artist_name}, Streams: {total_streams}, "
                f"Distinct Tracks: {distinct_tracks_listened}, Total Duration: {formatted_duration}")
        
        #streams per distinctive genres per user 
        distinctive_genres_per_user = await user_service.get_user_genre_stats(user_id)
        print("Distinctive Genres per User:")
        for row in distinctive_genres_per_user:
            genre = row["genre"]
            total_streams = row["total_streams"]
            print(f"Genre: {genre}, Streams: {total_streams}")

        #monthly stats
        monthly_stats = await user_service.get_monthly_stats(user_id)
        print("Monthly Stats:")
        for stats in monthly_stats:
            month = stats["month"]
            total_songs_listened = stats["total_songs_listened"]
            total_duration_minutes = stats["total_duration_minutes"]
            total_duration_hours = stats["total_duration_hours"]
            print(f"Month: {month}, total_songs_listened: {total_songs_listened}, "
                  f"total_duration_minutes: {total_duration_minutes} minutes, "
                  f"total_duration_hours: {total_duration_hours} hours")





        spotify_client = SpotifyClient(token)
        playing_now_data = await spotify_client.get_now_playing() or {
            "track_name": "N/A",
            "artists": "N/A",
            "album_image_url": "N/A"
        }

    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"Error fetching dashboard data: {str(e)}\nTraceback:\n{error_traceback}")
        return JSONResponse(content={"error": "An unexpected error occurred."}, status_code=500)
    finally:
        if db:
            await db.close()

    context = {
        "request": request,
        "user_id": user_id,
        "user_info": user_info,
        "top_artist_list": top_artist_list,
        "top_tracks_list": top_tracks_list,
        "track_play_counts": track_play_counts,
        "daily_play_count": daily_play_count,
        "total_play_count": total_play_count,
        "total_play_today": total_play_today,
        "daily_listening_time": daily_listening_time,
        "total_listened_minutes": total_listened_minutes,
        "total_listened_hours": total_listened_hours,
        "top_genres": top_genres,
        "records_by_time": records_by_time,
        "playing_now_data": playing_now_data,
        "current_time_range": time_range,
        "user_image": user_info.get("image_url") if user_info else None,
        "user_name": user_info.get("display_name") if user_info else "Unknown User",
        "track_name": playing_now_data.get("track_name"),
        "artist_name": playing_now_data.get("artists"),
        "album_img": playing_now_data.get("album_image_url")
    }

    return templates.TemplateResponse("dashboard.html", context)



@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    access_token = request.session.get("spotify_token")
    client_data = SpotifyClient(access_token)

    user_image, user_name = None, "Guest"
    user_info_dict = {}
    user_id = None

    if access_token:
        db = await get_db_connection()

        # Get user info from Spotify and update DB
        user_profile = await client_data.get_spotify_user_profile()
        spotify_user = SpotifyUser(access_token)
        user_data = await spotify_user.store_user_info_to_database(user_profile, db)
        user_id = user_data["id"]

        # Get additional user settings from DB
        stmt = select(
            User.user_id,
            User.image_url,
            User.display_name,
            User.custom_username,
            User.bio,
            User.preferred_language,
            User.timezone
        ).where(User.user_id == user_id)

        result = await db.execute(stmt)
        user_info = result.one_or_none()

        if user_info:
            user_info_dict = dict(user_info._mapping)
            user_image = user_info_dict["image_url"]
            user_name = user_info_dict["display_name"]
        else:
            user_name = "Unknown User"

        # Save user_id to session
        request.session["spotify_user_id"] = user_id

        await db.close()

    if not access_token or not user_id or user_name == "Guest":
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("profile.html", {
        "request": request,
        "current_path": request.url.path,  # ✅ Add this line
        "user_image": user_image,
        "user_name": user_name,
        "user_id": user_id,
        "custom_username": user_info_dict.get("custom_username", ""),
        "bio": user_info_dict.get("bio", ""),
        "language": user_info_dict.get("preferred_language", ""),
        "timezone": user_info_dict.get("timezone", "")
    })



@app.post("/update_settings")
async def update_settings(
    request: Request,
    custom_username: str = Form(...),
    bio: str = Form(...),
    language: str = Form(...),
    timezone: str = Form(...)
):
    user_id = request.session.get("spotify_user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    db = await get_db_connection()

    stmt = (
        update(User)
        .where(User.user_id == user_id)
        .values(
            custom_username=custom_username.strip() or None,
            bio=bio.strip() or None,
            preferred_language=language.strip() or None,
            timezone=timezone.strip() or None,
            last_updated=datetime.utcnow()
        )
    )

    await db.execute(stmt)
    await db.commit()
    await db.close()

    return RedirectResponse(url="/profile", status_code=303)





from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

@app.get("/get-more-history")
async def get_more_history(page: int = 1, db=Depends(get_db_connection), user_data: dict = Depends(SpotifyHandler.get_current_user)):

    user_id = user_data["user_id"]  # Extract user_id if needed

    limit = 20
    offset = (page - 1) * limit

    grouped = await MusicDataService.complete_listening_history(user_id, db, limit, offset)
    print(f"Fetched page {page} with {len(grouped)} records.")
    return JSONResponse(content=grouped)




@app.get("/listening-history", response_class=HTMLResponse)
async def show_listening_history(request: Request, db=Depends(get_db_connection), user_data: dict = Depends(SpotifyHandler.get_current_user)):
    user_id = user_data["user_id"]
    limit = 20
    offset = 0

    grouped_history = await MusicDataService.complete_listening_history(user_id, db, limit, offset)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "records_by_time": grouped_history  # 👈 match the name used in HTML
    })





    # recent tracks artist and image_url update
    #cursor.execute("SELECT track_id FROM listening_history WHERE user_id = %s;", (user_id,))
    #track_ids = cursor.fetchall()
    #all_tracks = get_track(token, track_ids)
    #all_artist_id_and_image_url_into_database(all_tracks, user_id)

    #cursor.execute("SELECT track_id FROM listening_history WHERE user_id = %s;", (user_id,))
    #track_ids = [row[0] for row in cursor.fetchall()]  # Extract track IDs as a list

    #if track_ids:  # Ensure there are tracks before calling API
        #get_tracks(token, track_ids)  # Fetch in batches
    #all_artist_id_and_image_url_into_database(all_tracks, user_id)  # Update DB


    #cursor.execute("SELECT track_id FROM listening_history WHERE user_id = %s;", (user_id,))
    #track_ids = [row[0] for row in cursor.fetchall()]  # Extract track IDs as a list

    #if track_ids:  # Ensure there are tracks before calling API
        #track_data = get_track(token, track_ids)  # Fetch in batches
        #all_artist_id_and_image_url_into_database(track_data, user_id) 






# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})

@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    db = await get_db_connection()
    access_token = request.session.get("spotify_token")
    client_data = SpotifyClient(access_token)
    user_profile = await client_data.get_spotify_user_profile()
    spotify_user = SpotifyUser(access_token)
    user_data = await spotify_user.store_user_info_to_database(user_profile, db)
    user_id = user_data["id"]

    # recent tracks artist and image_url update
    # cursor.execute("SELECT track_id FROM listening_history WHERE user_id = %s;", (user_id,))
    # track_ids = "2mlNgAeIBnL78ZriXgrRHz"  # Example track ID
    # all_tracks = get_track(token, track_ids)
    # print("all_tracks: ", all_tracks)
    # all_artist_id_and_image_url_into_database(all_tracks, user_id)




    if not file.filename.endswith(".zip"):
        return {"error": "Please upload a ZIP file"}

    # Extract ZIP file
    zip_data = await file.read()
    with zipfile.ZipFile(BytesIO(zip_data), 'r') as zip_ref:
        json_files = [name for name in zip_ref.namelist() if name.endswith(".json")]

        if not json_files:
            return {"error": "No JSON files found in ZIP"}

        records = []

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                for json_file in json_files:
                    with zip_ref.open(json_file) as f:
                        data = json.load(f)
                        print("Starting to process data")
                        for entry in data:
                            if not entry.get("master_metadata_track_name"):
                                continue  # Skip entries without track info

                            # For now, skip fetching artist/album data and store track info
                            track_id = entry.get("spotify_track_uri")
                            records.append(
                                (
                                    user_id,
                                    track_id,
                                    entry.get("master_metadata_track_name"),
                                    None,  # No artist_id for now
                                    entry.get("master_metadata_album_artist_name"),
                                    entry.get("master_metadata_album_album_name"),
                                    None,  # No album_image_url for now
                                    entry.get("ts"),
                                    entry.get("ms_played")
                                )
                            )

                # Insert into database without artist_id and album_image_url
                cursor.executemany(
                    """
                    INSERT INTO listening_history (
                        user_id, track_id, track_name, artist_id, artist_name,
                        album_name, album_image_url, played_at, duration_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, played_at) DO NOTHING;
                    """,
                    records
                )
                print("Inserted records into database: ", len(records))
                conn.commit()

    return {"message": f"Inserted {len(records)} records into database"}
    



import requests

def test_track_ids(token, track_ids):
    url_template = "https://api.spotify.com/v1/tracks/{}"  # API endpoint for a single track

    headers = {"Authorization": f"Bearer {token}"}

    for track_id in track_ids:
        url = url_template.format(track_id)
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            track_data = response.json()
            artist_id = track_data.get("artists", [{}])[0].get("id", None)
            album_image_url = track_data.get("album", {}).get("images", [{}])[0].get("url", None)
            print(f"Track {track_id}: Artist ID: {artist_id}, Album Image: {album_image_url}")
        else:
            print(f"Failed to fetch track 1 {track_id}: {response.status_code} - {response.text}")



