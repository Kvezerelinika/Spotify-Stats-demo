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
from typing import Optional


# Import Spotify helper functions
from app.oauth import OAuthSettings, SpotifyOAuth, SpotifyHandler, SpotifyUser
from app.spotify_api import SpotifyClient
from app.database import get_db_connection, AsyncSessionLocal
from app.helpers import MusicDataService, UserMusicUpdater, TokenRefresh
from app.db import User, Track, Album, Artist, UsersTopTracks, UsersTopArtists, ListeningHistory
from app.routers import messages
from app.dependencies import get_current_user

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
app.include_router(messages.router)

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
            
        # First song listened
        first_last_listened = await user_service.get_first_and_last_listened()
        print(f"first_last_listened: {first_last_listened}")

        # Unique numbers of artists and tracks
        unique_artists_count = await user_service.get_unique_listening_counts()
        print(f"Unique artists count: {unique_artists_count}")

        # Get currently playing track
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


# /users/{user_id}	
# Endpoint to fetch user profile data for other users
@app.get("/users/{user_id}", response_class=HTMLResponse)
async def get_user_profile(request: Request, user_id: str, db=Depends(get_db_connection)):
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

    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    user_info_dict = dict(user_info._mapping)

    return templates.TemplateResponse("user_profile.html", {
        "request": request,
        "user_info": user_info_dict,
    })

# /tracks/{track_id}
@app.get("/tracks/{track_id}")
async def get_track_details(request: Request, track_id: str, db=Depends(get_db_connection), current_user: dict = Depends(get_current_user)):
    # Fetch track details
    stmt = select(
        Track.track_id,
        Track.name,
        Track.album_id,
        Track.artist_id,
        Track.artist_name,
        Track.spotify_url,
        Track.duration_ms,
        Track.popularity,
        Track.explicit,
        Track.track_number,
        Track.album_release_date,
        Track.album_image_url,
        Track.album_name
    ).where(Track.track_id == track_id)
    
    result = await db.execute(stmt)
    track_info = result.one_or_none()

    if not track_info:
        raise HTTPException(status_code=404, detail="Track not found")

    track_info_dict = dict(track_info._mapping)

    # Fetch personal stats if user is logged in
    personal_stats = None
    if current_user:
        user_id = current_user["user_id"]
        stmt_history = select(ListeningHistory).where(
            ListeningHistory.track_id == track_id,
            ListeningHistory.user_id == user_id
        )
        history_result = await db.execute(stmt_history)
        history_entries = history_result.scalars().all()

        if history_entries:
            total_plays = len(history_entries)
            last_played = max(entry.played_at for entry in history_entries)
            first_played = min(entry.played_at for entry in history_entries)
            unique_days = {entry.played_at.date() for entry in history_entries}
            days_played = len(unique_days)
            from collections import Counter
            most_common_hour = Counter([entry.played_at.hour for entry in history_entries]).most_common(1)

            stmt_total = select(func.count()).where(ListeningHistory.user_id == user_id)
            total_listens = await db.scalar(stmt_total)

            percentage = (total_plays / total_listens) * 100 if total_listens else 0

            personal_stats = {
                "total_plays": total_plays,
                "last_played": last_played,
                "first_played": first_played,
                "days_played": days_played,
                "most_common_hour": most_common_hour[0][0] if most_common_hour else None,
                "percentage_of_total": round(percentage, 2),
                
            }

    return templates.TemplateResponse("track_details.html", {
        "request": request,
        "track_info": track_info_dict,
        "personal_stats": personal_stats,
    })

# /albums/{album_id}	
from sqlalchemy import func

@app.get("/albums/{album_id}")
async def get_album_details(request: Request, album_id: str, db=Depends(get_db_connection), user_id: Optional[str] = None):
    # Basic album info
    stmt = (
        select(
            Album.album_id,
            Album.name.label("album_name"),
            Album.release_date,
            Album.image_url,
            Album.spotify_url,
            Album.total_tracks,
            Artist.artist_id,
            Artist.name.label("artist_name")
        )
        .join(Artist, Album.artist_id == Artist.artist_id)
        .where(Album.album_id == album_id)
    )
    result = await db.execute(stmt)
    album_info = result.one_or_none()

    if not album_info:
        raise HTTPException(status_code=404, detail="Album not found")

    album_info_dict = dict(album_info._mapping)

    # --- Additional Stats ---
    # 1. Get track IDs for this album
    track_stmt = select(Track.track_id, Track.name).where(Track.album_id == album_id)
    tracks_result = await db.execute(track_stmt)
    tracks = tracks_result.fetchall()
    track_ids = [t.track_id for t in tracks]
    track_names = {t.track_id: t.name for t in tracks}

    # 2. Global stats
    global_listens_stmt = (
        select(
            ListeningHistory.track_id,
            func.count().label("listen_count")
        )
        .where(ListeningHistory.track_id.in_(track_ids))
        .group_by(ListeningHistory.track_id)
        .order_by(func.count().desc())
    )
    global_listens_result = await db.execute(global_listens_stmt)
    global_listens = global_listens_result.fetchall()

    # Most played track globally
    most_played_track_id = global_listens[0].track_id if global_listens else None
    most_played_track_name = track_names.get(most_played_track_id, "N/A") if most_played_track_id else "N/A"
    total_album_listens = sum([r.listen_count for r in global_listens])

    # 3. User-specific stats (if user_id is provided, e.g., from session)
    user_stats = {}
    if user_id:
        user_listens_stmt = (
            select(
                ListeningHistory.track_id,
                func.count().label("play_count"),
                func.min(ListeningHistory.played_at).label("first_play"),
                func.max(ListeningHistory.played_at).label("last_play")
            )
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.track_id.in_(track_ids)
            )
            .group_by(ListeningHistory.track_id)
            .order_by(func.count().desc())
        )
        user_listens_result = await db.execute(user_listens_stmt)
        user_listens = user_listens_result.fetchall()

        if user_listens:
            favorite_track_id = user_listens[0].track_id
            user_stats = {
                "total_listens": sum([r.play_count for r in user_listens]),
                "first_play": min([r.first_play for r in user_listens]),
                "last_play": max([r.last_play for r in user_listens]),
                "favorite_track": track_names.get(favorite_track_id)
            }

    return templates.TemplateResponse("album_details.html", {
        "request": request,
        "album_info": album_info_dict,
        "most_played_track": most_played_track_name,
        "total_album_listens": total_album_listens,
        "user_stats": user_stats,
    })


# /artists/{artist_id}	
@app.get("/artists/{artist_id}")
async def get_artist_details(request: Request, artist_id: str, db=Depends(get_db_connection)):
    # Fetch artist details from the database
    stmt = (
        select(
            Artist.artist_id,
            Artist.name.label("artist_name"),
            Artist.image_url,
            Artist.spotify_url,
            Artist.popularity,
            Artist.genres
        )
        .where(Artist.artist_id == artist_id)
    )

    result = await db.execute(stmt)
    artist_info = result.one_or_none()

    if not artist_info:
        raise HTTPException(status_code=404, detail="Artist not found")

    artist_info_dict = dict(artist_info._mapping)

    return templates.TemplateResponse("artist_details.html", {
        "request": request,
        "artist_info": artist_info_dict,
    })

# /genres/{genre_name}	
from sqlalchemy import func
from math import ceil

@app.get("/genres/{genre_name}")
async def get_genre_details(
    request: Request,
    genre_name: str,
    db=Depends(get_db_connection),
    search: str = "",
    sort: str = "popularity",  # or "release_date"
    page: int = 1,
    limit: int = 10
):
    offset = (page - 1) * limit

    # 1. Get artists matching genre
    artist_stmt = select(
        Artist.artist_id,
        Artist.name,
        Artist.image_url,
        Artist.spotify_url
    ).where(Artist.genres.any(genre_name))

    artist_result = await db.execute(artist_stmt)
    genre_artists = [dict(row._mapping) for row in artist_result.fetchall()]
    artist_ids = [a["artist_id"] for a in genre_artists]

    if not artist_ids:
        raise HTTPException(status_code=404, detail="Genre not found")

    # 2. Filtered track list (with search and sorting)
    track_stmt = select(
        Track.track_id,
        Track.name.label("track_name"),
        Track.artist_id,
        Track.artist_name,
        Track.album_name,
        Track.album_image_url,
        Track.spotify_url
    ).where(Track.artist_id.in_(artist_ids))

    if search:
        track_stmt = track_stmt.where(Track.name.ilike(f"%{search}%"))

    if sort == "popularity":
        track_stmt = track_stmt.order_by(Track.popularity.desc())
    elif sort == "release_date":
        track_stmt = track_stmt.order_by(Track.release_date.desc())

    track_count_stmt = select(func.count()).select_from(track_stmt.subquery())
    track_count = (await db.execute(track_count_stmt)).scalar_one()
    total_pages = ceil(track_count / limit)

    track_stmt = track_stmt.offset(offset).limit(limit)
    track_result = await db.execute(track_stmt)
    genre_tracks = [dict(row._mapping) for row in track_result.fetchall()]

    # 3. Albums (optional: same pagination logic)
    album_stmt = select(
        Album.album_id,
        Album.name.label("album_name"),
        Album.artist_id,
        Album.image_url,
        Album.spotify_url,
        Album.release_date
    ).where(Album.artist_id.in_(artist_ids))

    if sort == "release_date":
        album_stmt = album_stmt.order_by(Album.release_date.desc())

    album_result = await db.execute(album_stmt)
    genre_albums = [dict(row._mapping) for row in album_result.fetchall()]

    return templates.TemplateResponse("genre_details.html", {
        "request": request,
        "genre_name": genre_name,
        "genre_artists": genre_artists,
        "genre_tracks": genre_tracks,
        "genre_albums": genre_albums,
        "search": search,
        "sort": sort,
        "page": page,
        "total_pages": total_pages
    })




@app.get("/compare/{user_id_1}/{user_id_2}")
async def compare_users(
    request: Request,
    user_id_1: str,
    user_id_2: str,
    db=Depends(get_db_connection)
):
    # Fetch user profiles
    stmt = select(
        User.user_id,
        User.image_url,
        User.display_name,
        User.custom_username,
        User.bio
    ).where(User.user_id.in_([user_id_1, user_id_2]))

    result = await db.execute(stmt)
    users_info = {row.user_id: dict(row._mapping) for row in result.fetchall()}

    if user_id_1 not in users_info or user_id_2 not in users_info:
        raise HTTPException(status_code=404, detail="One or both users not found")

    # Fetch top artists for both users
    top_artists_stmt = (
        select(
            UsersTopArtists.user_id,
            Artist.artist_id,
            Artist.name.label("artist_name"),
            Artist.image_url,
            Artist.spotify_url,
            UsersTopArtists.rank
        )
        .join(Artist, Artist.artist_id == UsersTopArtists.artist_id)
        .where(UsersTopArtists.user_id.in_([user_id_1, user_id_2]))
        .order_by(UsersTopArtists.rank)
    )

    # Fetch top tracks for both users
    top_tracks_stmt = (
        select(
            UsersTopTracks.user_id,
            Track.track_id,
            Track.name.label("track_name"),
            Track.artist_name,
            Track.album_name,
            Track.album_image_url,
            Track.spotify_url,
            UsersTopTracks.rank
        )
        .join(Track, Track.track_id == UsersTopTracks.track_id)
        .where(UsersTopTracks.user_id.in_([user_id_1, user_id_2]))
        .order_by(UsersTopTracks.rank)
    )

    top_artists_result = await db.execute(top_artists_stmt)
    top_tracks_result = await db.execute(top_tracks_stmt)

    top_artists_by_user = {}
    top_tracks_by_user = {}

    for row in top_artists_result.fetchall():
        uid = row.user_id
        if uid not in top_artists_by_user:
            top_artists_by_user[uid] = []
        top_artists_by_user[uid].append(dict(row._mapping))

    for row in top_tracks_result.fetchall():
        uid = row.user_id
        if uid not in top_tracks_by_user:
            top_tracks_by_user[uid] = []
        top_tracks_by_user[uid].append(dict(row._mapping))

    # Get list data or empty
    artists_1 = top_artists_by_user.get(user_id_1, [])
    artists_2 = top_artists_by_user.get(user_id_2, [])
    tracks_1 = top_tracks_by_user.get(user_id_1, [])
    tracks_2 = top_tracks_by_user.get(user_id_2, [])

    # Shared artists
    ids_1 = {a["artist_id"] for a in artists_1}
    ids_2 = {a["artist_id"] for a in artists_2}
    shared_artist_ids = ids_1 & ids_2
    shared_artists = [a for a in artists_1 if a["artist_id"] in shared_artist_ids]
    artist_overlap_percent = round(len(shared_artist_ids) / max(len(ids_1 | ids_2), 1) * 100, 1)

    # Shared tracks
    tid_1 = {t["track_id"] for t in tracks_1}
    tid_2 = {t["track_id"] for t in tracks_2}
    shared_track_ids = tid_1 & tid_2
    shared_tracks = [t for t in tracks_1 if t["track_id"] in shared_track_ids]
    track_overlap_percent = round(len(shared_track_ids) / max(len(tid_1 | tid_2), 1) * 100, 1)

    has_overlap = bool(shared_artists or shared_tracks)

    return templates.TemplateResponse("compare_users.html", {
        "request": request,
        "user_info_1": users_info[user_id_1],
        "user_info_2": users_info[user_id_2],
        "shared_artists": shared_artists,
        "shared_tracks": shared_tracks,
        "artist_overlap_percent": artist_overlap_percent,
        "track_overlap_percent": track_overlap_percent,
        "has_overlap": has_overlap
    })



# /search?q=...	
@app.get("/search")
async def search(request: Request, q: str = Query(..., min_length=1), db=Depends(get_db_connection), limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)
):
    # Search for tracks, artists, and albums
    search_results = {
        "tracks": [],
        "artists": [],
        "albums": []
    }

    # Search tracks
    track_stmt = select(
        Track.track_id,
        Track.name.label("track_name"),
        Track.artist_name,
        Track.album_name,
        Track.album_image_url,
        Track.spotify_url
    ).where(Track.name.ilike(f"%{q}%")).offset(offset).limit(limit)

    track_result = await db.execute(track_stmt)
    search_results["tracks"] = [dict(row._mapping) for row in track_result.fetchall()]

    # Search artists
    artist_stmt = select(
        Artist.artist_id,
        Artist.name.label("artist_name"),
        Artist.image_url,
        Artist.spotify_url
    ).where(Artist.name.ilike(f"%{q}%")).offset(offset).limit(limit)

    artist_result = await db.execute(artist_stmt)
    search_results["artists"] = [dict(row._mapping) for row in artist_result.fetchall()]

    # Search albums
    album_stmt = select(
        Album.album_id,
        Album.name.label("album_name"),
        Album.artist_id,
        Album.image_url,
        Album.spotify_url
    ).where(Album.name.ilike(f"%{q}%")).offset(offset).limit(limit)

    album_result = await db.execute(album_stmt)
    search_results["albums"] = [dict(row._mapping) for row in album_result.fetchall()]

    return templates.TemplateResponse("search_results.html", {
        "request": request,
        "query": q,
        "search_results": search_results
    })

# /trending or /explore	Global stats — most listened artists/tracks across the platform.
@app.get("/trending")   
async def trending(request: Request, db=Depends(get_db_connection)):
    # Fetch global stats for trending artists and tracks
    stmt = select(
        Artist.artist_id,
        Artist.name.label("artist_name"),
        Artist.image_url,
        Artist.spotify_url,
        func.count(Track.track_id).label("total_streams")
    ).join(Track, Track.artist_id == Artist.artist_id).group_by(Artist.artist_id).order_by(func.count(Track.track_id).desc()).limit(10)

    result = await db.execute(stmt)
    trending_artists = [dict(row._mapping) for row in result.fetchall()]

    track_stmt = select(
        Track.track_id,
        Track.name.label("track_name"),
        Track.artist_name,
        Track.album_name,
        Track.album_image_url,
        Track.spotify_url,
        func.count().label("total_streams")
    ).group_by(Track.track_id).order_by(func.count().desc()).limit(10)

    track_result = await db.execute(track_stmt)
    trending_tracks = [dict(row._mapping) for row in track_result.fetchall()]

    return templates.TemplateResponse("trending.html", {
        "request": request,
        "trending_artists": trending_artists,
        "trending_tracks": trending_tracks
    })

# /history or /timeline	Personal listening history (calendar/timeline view).

# /messages, /notifications 
@app.get("/messages-page")
async def messages_page(request: Request):
    return templates.TemplateResponse("messages.html", {"request": request})

# STREAMS BY DAY OF THE WEEK
@app.get("/streams-by-day")
async def streams_by_day(request: Request, db=Depends(get_db_connection), user_data: dict = Depends(SpotifyHandler.get_current_user)):
    user_id = user_data["user_id"]
    # Fetch streams by day of the week
    stmt = select(
        func.to_char(Track.played_at, 'Day').label('day_of_week'),
        func.count(Track.track_id).label('stream_count')
    ).where(Track.user_id == user_id).group_by(func.to_char(Track.played_at, 'Day')).order_by(func.to_char(Track.played_at, 'Day'))
    result = await db.execute(stmt)
    streams_by_day = {row.day_of_week.strip(): row.stream_count for row in result.fetchall()}
    # Ensure all days are present in the result
    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for day in days_of_week:
        if day not in streams_by_day:
            streams_by_day[day] = 0
    return templates.TemplateResponse("streams_by_day.html", {
        "request": request,
        "streams_by_day": streams_by_day
    })

#STREAMS BY MONTH OF THE YEAR
@app.get("/streams-by-month")
async def streams_by_month(request: Request, db=Depends(get_db_connection), user_data: dict = Depends(SpotifyHandler.get_current_user)):
    user_id = user_data["user_id"]
    # Fetch streams by month of the year
    stmt = select(
        func.to_char(Track.played_at, 'Month').label('month'),
        func.count(Track.track_id).label('stream_count')
    ).where(Track.user_id == user_id).group_by(func.to_char(Track.played_at, 'Month')).order_by(func.to_char(Track.played_at, 'Month'))
    result = await db.execute(stmt)
    streams_by_month = {row.month.strip(): row.stream_count for row in result.fetchall()}
    # Ensure all months are present in the result
    months_of_year = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    for month in months_of_year:
        if month not in streams_by_month:
            streams_by_month[month] = 0
    return templates.TemplateResponse("streams_by_month.html", {
        "request": request,
        "streams_by_month": streams_by_month
    })

#ON THIS DAY YOU LISTENED
@app.get("/on-this-day")
async def on_this_day(request: Request, db=Depends(get_db_connection), user_data: dict = Depends(SpotifyHandler.get_current_user)):
    user_id = user_data["user_id"]
    today = datetime.now(timezone.utc).date()

    # Fetch tracks listened to on this day in previous years
    stmt = select(
        Track.track_id,
        Track.name.label("track_name"),
        Track.artist_name,
        Track.album_name,
        Track.album_image_url,
        Track.spotify_url,
        func.date(Track.played_at).label("listened_date")
    ).where(
        func.date(Track.played_at) == today
    ).where(Track.user_id == user_id)

    result = await db.execute(stmt)
    tracks_today = [dict(row._mapping) for row in result.fetchall()]

    return templates.TemplateResponse("on_this_day.html", {
        "request": request,
        "tracks_today": tracks_today,
        "today": today
    })

#TODAYS TOPS
@app.get("/todays-tops")
async def todays_tops(request: Request, db=Depends(get_db_connection), user_data: dict = Depends(SpotifyHandler.get_current_user)):
    user_id = user_data["user_id"]
    today = datetime.now(timezone.utc).date()

    # Fetch today's top tracks
    stmt = select(
        Track.track_id,
        Track.name.label("track_name"),
        Track.artist_name,
        Track.album_name,
        Track.album_image_url,
        Track.spotify_url,
        func.count(Track.track_id).label("stream_count")
    ).where(
        func.date(Track.played_at) == today,
        Track.user_id == user_id
    ).group_by(
        Track.track_id, Track.name, Track.artist_name, Track.album_name, Track.album_image_url, Track.spotify_url
    ).order_by(func.count(Track.track_id).desc()).limit(10)

    result = await db.execute(stmt)
    top_tracks_today = [dict(row._mapping) for row in result.fetchall()]

    return templates.TemplateResponse("todays_tops.html", {
        "request": request,
        "top_tracks_today": top_tracks_today,
        "today": today
    })

#ALL ARTIST LISTENED BY STREAMS
@app.get("/all-artists")
async def all_artists(request: Request, db=Depends(get_db_connection), user_data: dict = Depends(SpotifyHandler.get_current_user)):
    user_id = user_data["user_id"]

    # Fetch all artists listened to by the user, ordered by total streams
    stmt = select(
        Artist.artist_id,
        Artist.name.label("artist_name"),
        Artist.image_url,
        Artist.spotify_url,
        func.count(Track.track_id).label("total_streams")
    ).join(Track, Track.artist_id == Artist.artist_id).where(Track.user_id == user_id).group_by(
        Artist.artist_id, Artist.name, Artist.image_url, Artist.spotify_url
    ).order_by(func.count(Track.track_id).desc())

    result = await db.execute(stmt)
    all_artists = [dict(row._mapping) for row in result.fetchall()]

    return templates.TemplateResponse("all_artists.html", {
        "request": request,
        "all_artists": all_artists
    })

#GLOBAL RANK PER ARTIST
@app.get("/global-artist-rank")
async def global_artist_rank(request: Request, db=Depends(get_db_connection), user_data: dict = Depends(SpotifyHandler.get_current_user)):
    user_id = user_data["user_id"]

    # Fetch global artist rank based on total streams
    stmt = select(
        Artist.artist_id,
        Artist.name.label("artist_name"),
        Artist.image_url,
        Artist.spotify_url,
        func.count(Track.track_id).label("total_streams")
    ).join(Track, Track.artist_id == Artist.artist_id).where(Track.user_id == user_id).group_by(
        Artist.artist_id, Artist.name, Artist.image_url, Artist.spotify_url
    ).order_by(func.count(Track.track_id).desc())

    result = await db.execute(stmt)
    global_artist_rank = [dict(row._mapping) for row in result.fetchall()]

    return templates.TemplateResponse("global_artist_rank.html", {
        "request": request,
        "global_artist_rank": global_artist_rank
    })

#GLOBAL RANK PER SONG
@app.get("/global-song-rank")
async def global_song_rank(request: Request, db=Depends(get_db_connection), user_data: dict = Depends(SpotifyHandler.get_current_user)):
    user_id = user_data["user_id"]

    # Fetch global song rank based on total streams
    stmt = select(
        Track.track_id,
        Track.name.label("track_name"),
        Track.artist_name,
        Track.album_name,
        Track.album_image_url,
        Track.spotify_url,
        func.count(Track.track_id).label("total_streams")
    ).where(Track.user_id == user_id).group_by(
        Track.track_id, Track.name, Track.artist_name, Track.album_name, Track.album_image_url, Track.spotify_url
    ).order_by(func.count(Track.track_id).desc())

    result = await db.execute(stmt)
    global_song_rank = [dict(row._mapping) for row in result.fetchall()]

    return templates.TemplateResponse("global_song_rank.html", {
        "request": request,
        "global_song_rank": global_song_rank
    })

# /users/{user_id}/followers See who follows this user.

# /users/{user_id}/following See which users they follow.

# /users/{user_id}/library	Personal saved albums, artists, tracks.

# /users/{user_id}/stats	Deep dive into listening patterns, streaks, genres, etc.


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



