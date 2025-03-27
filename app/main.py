from fastapi import FastAPI, Request, Query, HTTPException, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
import time, asyncio, zipfile, json, logging
from io import BytesIO


# Import Spotify helper functions
from app.oauth import get_spotify_token, get_spotify_login_url, user_info_to_database
from app.spotify_api import get_spotify_user_profile
from app.database import get_db_connection
from app.helpers import (get_user_info, get_top_artists_db, get_top_tracks_db, get_track_play_counts, get_daily_play_counts, get_total_play_count, get_total_play_today, get_current_playing, get_total_listening_time, get_daily_listening_time, get_top_genres, update_user_music_data, complete_listening_history)

# Initialize FastAPI only once
app = FastAPI()

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
    token = request.session.get("spotify_token")

    # Default values in case the user is not logged in
    user_image, user_name = None, "Guest"

    # If the user is logged in, fetch user profile data
    if token:
        db = get_db_connection()
        cursor = db.cursor()

        # Get the user profile from Spotify
        user_profile = get_spotify_user_profile(token)
        user_data = user_info_to_database(user_profile)
        user_id = user_data[0][0]

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
async def layout_page(request: Request):
    db = get_db_connection()
    cursor = db.cursor()

    token = request.session.get("spotify_token")
    user_profile = get_spotify_user_profile(token)
    user_data = user_info_to_database(user_profile)
    user_id = user_data[0][0]

    cursor.execute("SELECT images, display_name FROM users WHERE id = %s;", (user_id,))
    user_info = cursor.fetchone()  # Fetch only once
    if user_info:
        user_image, user_name = user_info  # Unpack values safely
    else:
        user_image, user_name = None, "Unknown User"  # Handle missing data

    return templates.TemplateResponse("layout.html", {
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
    return RedirectResponse(get_spotify_login_url(request))

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.get("/callback")
async def callback(request: Request):
    """Handle Spotify OAuth callback."""
    
    # Extract 'code' and 'state' from query parameters
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state in the callback")

    # Step 1: Verify the 'state' parameter to prevent CSRF attacks
    stored_state = request.session.get("spotify_auth_state")
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="State mismatch in callback. Possible CSRF attack.")

    try:
        # Step 2: Exchange the authorization code for an access token
        token_response = await get_spotify_token(code, state, request)

        if "access_token" in token_response:
            access_token = token_response["access_token"]

            # Store the access token in session
            request.session["spotify_token"] = access_token

            # Step 3: Fetch user data from Spotify
            user_info = await get_spotify_user_profile(access_token)

            # Step 4: Extract user_id from user info and store it in session
            user_id = user_info.get("id")
            if user_id:
                request.session["user_id"] = user_id  # Save user_id in session

            # Redirect to the dashboard (or another page)
            return RedirectResponse(url="/dashboard")
        else:
            raise HTTPException(status_code=400, detail="No access token returned.")
    
    except Exception as e:
        print(f"Error during token exchange: {str(e)}")
        return {"error": f"Error during token exchange: {str(e)}"}

# Function to fetch user data from Spotify
import time
import httpx

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

import asyncio, asyncpg
from concurrent.futures import ThreadPoolExecutor
import traceback, os


from fastapi import Request, APIRouter
from fastapi.responses import RedirectResponse, JSONResponse
import traceback

router = APIRouter()

@app.get("/dashboard")
async def dashboard(request: Request, limit: int = 1000, offset: int = 0):
    db = None
    try:
        token = request.session.get("spotify_token")
        user_id = request.session.get("user_id")

        if not token or not user_id:
            return RedirectResponse(url="/login")

        user_profile = await get_spotify_user_profile(token)
        if not user_profile:
            return JSONResponse(content={"error": "Failed to fetch user profile from Spotify."}, status_code=500)

        user_data = await user_info_to_database(user_profile)
        if user_data:
            new_user_id = user_data[0][0]
            if new_user_id != user_id:
                request.session["user_id"] = new_user_id

        db = await get_db_connection()
        time_range = request.query_params.get('time_range', 'medium_term')

        await asyncio.gather(
            update_user_music_data(user_id, token, "top_artists", time_range),
            update_user_music_data(user_id, token, "top_tracks", time_range),
            update_user_music_data(user_id, token, "recent_tracks", time_range)
        )

        (
            user_info,
            top_artist_list,
            top_tracks_list,
            track_play_counts,
            daily_play_count,
            total_play_count,
            total_play_today,
            total_listened_minutes,
            total_listened_hours,
            daily_listening_time,
            top_genres,
            records_by_time,
        ) = await asyncio.gather(
            get_user_info(user_id, db),
            get_top_artists_db(user_id, db, time_range),
            get_top_tracks_db(user_id, db),
            get_track_play_counts(user_id, db),
            get_daily_play_counts(user_id, db),
            get_total_play_count(user_id, db),
            get_total_play_today(user_id, db),
            get_total_listening_time(user_id, db),
            get_daily_listening_time(user_id, db),
            get_top_genres(user_id, db),
            complete_listening_history(user_id, db, limit, offset),
        )

        playing_now_data = await get_current_playing(token) or {
            "track_name": "N/A",
            "artist_name": "N/A",
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
        "user_id": request.session["user_id"],
        "track_play_counts": track_play_counts,
        "daily_play_counts": daily_play_count,
        "total_play_count": total_play_count,
        "total_play_today": total_play_today,
        "top_artist_list": top_artist_list,
        "top_genres": top_genres,
        "top_tracks_list": top_tracks_list,
        "total_listened_minutes": total_listened_minutes,
        "total_listened_hours": total_listened_hours,
        "daily_listening_time": daily_listening_time,
        "user_image": user_info[7] if user_info else None,
        "user_name": user_info[1] if user_info else "Unknown User",
        "track_name": playing_now_data.get("track_name"),
        "artist_name": playing_now_data.get("artist_name", "Unknown Artist"),
        "album_img": playing_now_data.get("album_image_url"),
        "records_by_time": records_by_time,
        "current_time_range": time_range
    }

    return templates.TemplateResponse("dashboard.html", context)













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
    token = request.session.get("spotify_token")
    user_profile = get_spotify_user_profile(token)
    user_data = user_info_to_database(user_profile)
    user_id = user_data[0][0] 

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



