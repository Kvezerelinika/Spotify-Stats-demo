from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime


# Import Spotify helper functions
from app.oauth import get_spotify_token, get_spotify_login_url, user_info_to_database
from app.spotify_api import get_top_artists, get_recently_played_tracks, get_spotify_user_profile, get_top_tracks, get_track
from app.crud import recents_to_database, top_artists_to_database, top_tracks_to_database, all_artist_id_and_image_url_into_database
from app.database import get_db_connection

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

    # Log the values for debugging
    print(f"Received code: {code}")
    print(f"Received state: {state}")

    # Step 1: Verify the 'state' parameter to prevent CSRF attacks
    stored_state = request.session.get("spotify_auth_state")
    print("stored_state: ", stored_state)
    print("state: ", state)
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="State mismatch in callback. Possible CSRF attack.")

    try:
        # Step 2: Pass the values to get_spotify_token to exchange the authorization code for an access token
        token_response = await get_spotify_token(code, state, request)

        # Ensure the response contains an access token
        if "access_token" in token_response:
            access_token = token_response["access_token"]

            # Store the access token in session
            request.session["spotify_token"] = access_token

            # Redirect to the dashboard or wherever you need
            return RedirectResponse(url="/dashboard")
        else:
            raise HTTPException(status_code=400, detail="No access token returned.")
    
    except Exception as e:
        # Log the error and return a response
        print(f"Error during token exchange: {str(e)}")
        return {"error": f"Error during token exchange: {str(e)}"}

# ---------------------------------------
# 🎵 2️⃣ Fetch & Display Spotify Data
# ---------------------------------------

@app.get("/dashboard")
async def dashboard(request: Request):
    db = get_db_connection()
    cursor = db.cursor()



    # Fetch user info
    token = request.session.get("spotify_token")
    print("TOKEN: ", token)
    user_profile = get_spotify_user_profile(token)
    user_data = user_info_to_database(user_profile)
    user_id = user_data[0][0] # If user_data is a list of dictionaries

    cursor.execute("SELECT images, display_name FROM users WHERE id = %s;", (user_id,))
    user_info = cursor.fetchone()  # Fetch only once
    if user_info:
        user_image, user_name = user_info  # Unpack values safely
    else:
        user_image, user_name = None, "Unknown User"  # Handle missing data

    # top artists
    top_artists = await get_top_artists(token)
    top_artists_to_database(top_artists, user_id)    

    cursor.execute("SELECT artist_name, image_url, spotify_url FROM users_top_artists WHERE user_id = %s ORDER BY id ASC;", (user_id,))
    top_artist_list = cursor.fetchall()

    # top tracks
    top_tracks = await get_top_tracks(token)
    top_tracks_to_database(top_tracks, user_id)

    cursor.execute("SELECT track_name, artist_name, popularity, album_image_url, spotify_url FROM top_tracks WHERE user_id = %s ORDER BY rank ASC;", (user_id,))
    top_tracks_list = cursor.fetchall()

    # recent tracks artist and image_url update
    #cursor.execute("SELECT track_id FROM listening_history WHERE user_id = %s;", (user_id,))
    #track_ids = cursor.fetchall()
    #all_tracks = get_track(token, track_ids)
    #all_artist_id_and_image_url_into_database(all_tracks, user_id)

    # recent tracks
    recent_tracks = await get_recently_played_tracks(token)  # Call the function
    recents_to_database(recent_tracks, user_id)  # Pass the returned data

    cursor.execute("""SELECT track_name, artist_name, album_image_url, COUNT(*) AS track_play_counts FROM listening_history WHERE user_id = %s GROUP BY track_name, artist_name, album_image_url ORDER BY track_play_counts DESC LIMIT 10;""", (user_id,))
    track_play_counts = cursor.fetchall()
         
    # Fetch daily play counts
    cursor.execute("""SELECT DATE(played_at) AS play_date, COUNT(*) AS daily_play_count FROM listening_history WHERE user_id = %s GROUP BY play_date ORDER BY play_date DESC;""", (user_id,))
    daily_play_count = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) AS total_play_count FROM listening_history WHERE user_id = %s;", (user_id,))
    total_play_count = cursor.fetchone()[0]

    # Fetching total plays today
    today = datetime.today().date()  # Get today's date
    cursor.execute("""SELECT COUNT(*) FROM listening_history WHERE user_id = %s AND DATE(played_at) = %s;""", (user_id, today))
    total_play_today = cursor.fetchone()[0] or 0

    cursor.execute("SELECT track_name AS current_track_name, artist_name AS current_artist_name, album_image_url AS current_album_image_url FROM listening_history WHERE user_id = %s ORDER BY played_at DESC LIMIT 1;", (user_id,))
    album_img = None

    if user_id:
        cursor.execute("SELECT track_name, artist_name, album_image_url FROM listening_history WHERE user_id = %s ORDER BY played_at DESC LIMIT 1;", (user_id,))
        playing_now_data = cursor.fetchone()
        if playing_now_data:
            track_name, artist_name, album_img = playing_now_data

    # Calculate total duration using a single SQL query
    cursor.execute("""
        SELECT SUM(duration_ms) 
        FROM listening_history 
        WHERE user_id = %s AND duration_ms IS NOT NULL;
    """, (user_id,))
    
    total_duration_ms = cursor.fetchone()[0] or 0  # Use 0 if result is None
    total_listened_min = total_duration_ms / 60000
    total_listened_minutes = int(total_listened_min)

    total_listened_h = total_listened_minutes / 60
    total_listened_hours = int(total_listened_h)

    # fetch daily minutes and hours listened
    cursor.execute("""SELECT DATE(played_at) AS play_date, SUM(duration_ms)/60000 AS daily_minutes, SUM(duration_ms)/3600000 AS daily_hours FROM listening_history WHERE user_id = %s AND duration_ms IS NOT NULL GROUP BY play_date ORDER BY play_date DESC;""", (user_id,))
    daily_listening_time = cursor.fetchall()

    # Get genres from top artists and count their frequency
    genres_count = {}
    for artist in top_artists.get("items", []):
        artist_genres = artist.get("genres", [])
        for genre in artist_genres:
            genres_count[genre] = genres_count.get(genre, 0) + 1

    # Sort genres by frequency and get top 10
    top_genres = sorted(genres_count.items(), key=lambda x: x[1], reverse=True)[:20]




    # Close DB connection
    cursor.close()
    db.close()

    # Return rendered template
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user_id": user_id,
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
            "user_image": user_image,
            "user_name": user_name,
            "track_name": track_name,
            "artist_name": artist_name,
            "album_img": album_img
        }
    )


import asyncio
import zipfile
import json
from io import BytesIO
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi import Request
import logging
from app.database import get_db_connection

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
    cursor.execute("SELECT track_id FROM listening_history WHERE user_id = %s;", (user_id,))
    track_ids = "2mlNgAeIBnL78ZriXgrRHz"  # Example track ID
    all_tracks = get_track(token, track_ids)
    print("all_tracks: ", all_tracks)
    all_artist_id_and_image_url_into_database(all_tracks, user_id)




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



