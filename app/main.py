from fastapi import FastAPI, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from collections import Counter

# Import Spotify helper functions
from app.oauth import get_spotify_token, get_spotify_login_url, exchange_code_for_token, user_info_to_database
from app.spotify_api import get_top_artists, get_recently_played_tracks, get_spotify_user_profile

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
def root(request: Request, token: str = Depends(get_spotify_token)):
    """Fetch top artists from Spotify and display on homepage."""
    if not token:
        return RedirectResponse("/login")

    top_artists = get_top_artists(token)  # Fetch data from Spotify API
    return templates.TemplateResponse("index.html", {"request": request, "top_artists": top_artists})

@app.get("/login-page")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/login")
def login():
    """Redirect user to Spotify's OAuth login."""
    return RedirectResponse(get_spotify_login_url())

@app.get("/callback")
async def callback(request: Request, code: str = None):
    """Handle Spotify OAuth callback."""
    if not code:
        return {"error": "Code is missing in the callback URL."}

    try:
        # Exchange the code for an access token
        token_data = exchange_code_for_token(code)
        access_token = token_data.get("access_token")

        # ✅ Store token in session
        request.session["spotify_token"] = access_token

        # Redirect to dashboard
        return RedirectResponse(url="/dashboard")

    except Exception as e:
        return {"error": str(e)}

# ---------------------------------------
# 🎵 2️⃣ Fetch & Display Spotify Data
# ---------------------------------------

@app.get("/dashboard")
async def dashboard(request: Request):
    """Render the dashboard page with top artists & recently played tracks."""
    
    # Fetch the Spotify token from session
    token = request.session.get("spotify_token")
    user_id = request.session.get("user_id")
    
    if not token:
        return RedirectResponse(url="/login")  # Redirect to login if token is missing

    # Fetch user info from Spotify API (using token)
    if not user_id:
        user_profile = get_spotify_user_profile(token)
        if user_profile:
            print("User Profile:", user_profile)  # Debugging the user profile response
            user_id = user_profile["id"]  # Assign the user ID from the profile to session
            request.session["user_id"] = user_id  # Store user ID in session
        
            # Insert user info into database
            get_user = user_info_to_database(user_profile)  # Pass user_profile (make sure it's a dictionary)
        else:
            print("Error: No user profile data")

    
    # Print user info if available
    if get_user is not None:
        print("User Info: ", get_user)  # This should now print user info or a meaningful message
    else:
        print("No user data available.")
    
    # Fetch recently played tracks and top artists
    recently_played_data = get_recently_played_tracks(token)
    top_artists = get_top_artists(token)
    
    recently_played = recently_played_data.get("items", [])
    
    if not recently_played:
        return {"error": "No recently played tracks found."}

    # Count occurrences of each track ID
    if isinstance(recently_played, list) and all(isinstance(track, dict) for track in recently_played):
        play_counts = Counter(track["track"]["id"] for track in recently_played)
        
        for track in recently_played:
            track["play_count"] = play_counts[track["track"]["id"]]

        return templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "recently_played": recently_played, "top_artists": top_artists}
        )
    else:
        return {"error": "Unexpected data format for recently played tracks"}
