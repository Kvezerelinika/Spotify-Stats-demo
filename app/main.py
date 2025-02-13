from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from collections import Counter
from collections import defaultdict
from datetime import datetime
import httpx

# Import Spotify helper functions
from app.oauth import get_spotify_token, get_spotify_login_url, user_info_to_database
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
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="State mismatch. Possible CSRF attack.")

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
    """Render the dashboard page with top artists & recently played tracks."""
    
    # Fetch the Spotify token from session
    token = request.session.get("spotify_token")
    
    if not token:
        return RedirectResponse(url="/login")  # Redirect to login if token is missing

    # Fetch user info from Spotify API (using token)
    url = "https://api.spotify.com/v1/me"
    headers = {
        "Authorization": f"Bearer {token}"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

    if response.status_code != 200:
        return {"error": "Error fetching user profile from Spotify"}

    user_profile = response.json()
    
    if user_profile:
        print("User Profile:", user_profile)  # Debugging the user profile response
        user_id = user_profile["id"]  # Assign the user ID from the profile to session
        request.session["user_id"] = user_id  # Store user ID in session
    
        # Insert user info into the database
        get_user = user_info_to_database(user_profile)  # Pass user_profile (make sure it's a dictionary)
    else:
        print("Error: No user profile data")

    
    # Print user info if available
    if get_user is not None:
        print("User Info: ", get_user)  # This should now print user info or a meaningful message
    else:
        print("No user data available.")
    
    # Fetch recently played tracks and top artists
    recently_played_data = await get_recently_played_tracks(token)
    top_artists = await get_top_artists(token)
    
    recently_played = recently_played_data.get("items", [])
    
    if not recently_played:
        return {"error": "No recently played tracks found."}

    # Count occurrences of each track ID
    if isinstance(recently_played, list) and all(isinstance(track, dict) for track in recently_played):
        # Dictionary to store total listens per day
        daily_listening_counts = defaultdict(int)

        # Dictionary to store total plays per track per day
        track_daily_counts = defaultdict(lambda: defaultdict(int))

        unique_tracks = []
        seen_tracks = set()

        for track in recently_played:
            track_id = track["track"]["id"]
            played_at = track["played_at"]  # Example: "2024-02-12T15:30:00Z"
            
            # Extract only the date part
            played_date = datetime.fromisoformat(played_at.replace("Z", "")).date()

            # Count occurrences of each track per day
            track_daily_counts[played_date][track_id] += 1
            daily_listening_counts[played_date] += 1  # Total listens for the day

            # Store only unique tracks
            if track_id not in seen_tracks:
                unique_tracks.append(track)
                seen_tracks.add(track_id)

        # Assign the play count per track (total daily plays)
        for track in unique_tracks:
            track_id = track["track"]["id"]
            played_at = track["played_at"]
            played_date = datetime.fromisoformat(played_at.replace("Z", "")).date()
            track["play_count"] = track_daily_counts[played_date][track_id]

        print("Daily Listening Counts:", dict(daily_listening_counts))  # Debugging

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "recently_played": unique_tracks,
                "top_artists": top_artists,
                "daily_listening_counts": dict(daily_listening_counts),
            }
        )
    else:
        return {"error": "Unexpected data format for recently played tracks"}


