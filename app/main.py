from fastapi import FastAPI, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from app.oauth import get_spotify_token, get_spotify_login_url, get_spotify_token, handle_spotify_callback, exchange_code_for_token
from app.spotify_api import get_top_artists
import requests


app = FastAPI()

# Set up session middleware to manage sessions
app.add_middleware(SessionMiddleware, secret_key="39e52e320acd494bb03a418878fa7dfe")

# Set up Jinja2 templates
templates = Jinja2Templates(directory="app/templates")

# Serve static files (CSS, JS, images)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
def root(request: Request, token: str = Depends(get_spotify_token)):
    """
    Fetch top artists from Spotify and display on homepage.
    """
    top_artists = get_top_artists(token)  # Fetch data from Spotify API
    return templates.TemplateResponse("index.html", {"request": request, "top_artists": top_artists})

@app.get("/login-page")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/login")
def login():
    # Redirect to Spotify's login URL
    return RedirectResponse(get_spotify_login_url()) 

@app.get("/callback")
async def callback(request: Request, code: str = None):
    """
    Handle Spotify callback and get the access token.
    """
    if not code:
        return {"error": "Code is missing in the callback URL. Make sure Spotify is redirecting properly."}
    
    try:
        # Exchange the code for an access token
        token_data = exchange_code_for_token(code)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")  # Optional, you can save this to refresh the token later

        # Store the token in a session or database
        request.session["spotify_token"] = access_token
        
        # Redirect to the dashboard or any other page
        return RedirectResponse(url="/dashboard")

    except Exception as e:
        return {"error": str(e)}

@app.get("/dashboard")
def dashboard(request: Request, token: str = Depends(get_spotify_token)):
    top_artists = get_top_artists(token)
    print(top_artists)  # Debug: Check if top_artists data is being fetched
    return templates.TemplateResponse("dashboard.html", {"request": request, "top_artists": top_artists})


@app.get("/api/top-artists")
def top_artists(request: Request):
    token = request.session.get("spotify_token")
    if not token:
        return {"error": "User not logged in"}
    
    return get_top_artists(token)
