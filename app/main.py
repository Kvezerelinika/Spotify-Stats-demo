from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

# Import Spotify helper functions
from app.oauth import get_spotify_token, get_spotify_login_url, user_info_to_database
from app.spotify_api import get_top_artists, get_recently_played_tracks, get_spotify_user_profile
from app.crud import recents_to_database, top_artists_to_database
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
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login-page")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/login")
def login(request: Request):
    return RedirectResponse(get_spotify_login_url(request))

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
    user_profile = get_spotify_user_profile(token)
    user_data = user_info_to_database(user_profile)
    user_id = user_data[0][0] # If user_data is a list of dictionaries

    top_artists = await get_top_artists(token)
    top_artists_to_database(top_artists, user_id)


    cursor.execute("SELECT artist_name FROM users_top_artists WHERE user_id = %s ORDER BY id ASC;", (user_id,))
    top_artist_list = cursor.fetchall()
    print("TOP ARTISTS: ", top_artist_list)


    # Store recent tracks in DB
    recent_tracks = await get_recently_played_tracks(token)  # Call the function
    recents_to_database(recent_tracks, user_id)  # Pass the returned data

    # Fetch track play counts
    cursor.execute("""SELECT track_name, COUNT(*) AS track_play_counts FROM listening_history WHERE user_id = %s GROUP BY track_name ORDER BY track_play_counts DESC;""", (user_id,))
    track_play_counts = cursor.fetchall()

    # Fetch daily play counts
    cursor.execute("""SELECT DATE(played_at) AS play_date, COUNT(*) AS daily_play_count FROM listening_history WHERE user_id = %s GROUP BY play_date ORDER BY play_date DESC;""", (user_id,))
    daily_play_count = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) AS total_play_count FROM listening_history WHERE user_id = %s;", (user_id,))
    total_play_count = cursor.fetchone()[0]

    # Close DB connection
    cursor.close()
    db.close()

    # Return rendered template
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "track_play_counts": track_play_counts,
            "daily_play_counts": daily_play_count,
            "total_play_count": total_play_count,
            "top_artist_list": top_artist_list
        }
    )

