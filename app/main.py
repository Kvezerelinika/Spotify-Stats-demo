from fastapi import FastAPI, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from collections import Counter

# Import Spotify helper functions
from app.oauth import get_spotify_token, get_spotify_login_url, exchange_code_for_token
from app.spotify_api import get_top_artists, get_recently_played_tracks

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
    
    if not token:
        return RedirectResponse(url="/login")  # Redirect to login if token is missing

    # Fetch recently played tracks using the token
    recently_played_data = get_recently_played_tracks(token)  # Pass token to the function
    
    # Debug print to inspect the structure of the response
    print("Recently Played Data:", recently_played_data)
    
    # Check if 'items' exists in the data and extract the list of tracks
    recently_played = recently_played_data.get("items", [])
    top_artists = get_top_artists(token)

    for index, artist in enumerate(top_artists['items'], start=1):
        print(f"{index}. {artist['name']} - {artist['external_urls']['spotify']}")
    
    if not recently_played:
        return {"error": "No recently played tracks found."}

    # Ensure 'recently_played' is a list of dictionaries
    if isinstance(recently_played, list) and all(isinstance(track, dict) for track in recently_played):
        # Count occurrences of each track ID
        play_counts = Counter(track["track"]["id"] for track in recently_played)

        # Add the play count to each track in the recently played list
        for track in recently_played:
            track["play_count"] = play_counts[track["track"]["id"]]

        return templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "recently_played": recently_played, "top_artists": top_artists}
        )
    else:
        # If the data is not in the expected format, return an error message
        return {"error": "Unexpected data format for recently played tracks"}

@app.get("/api/top-artists")
def api_top_artists(request: Request):
    """API Endpoint: Fetch user's top artists."""
    token = request.session.get("spotify_token")

    if not token:
        return {"error": "User not logged in"}

    top_artists = get_top_artists(token)  # ✅ Define variable before printing
    print("Top Artists:", top_artists)  # Debugging
    return top_artists
