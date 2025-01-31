from fastapi import FastAPI, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from app.oauth import get_spotify_token
from app.spotify_api import get_top_artists

app = FastAPI()

templates = Jinja2Templates(directory="app/templates")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
def root():
    return templates.TemplateResponse("index.html", {"request": Request})

@app.get("/login")
def login():
    # Redirects user to Spotify login URL
    return get_spotify_token()

@app.get("/api/top-artists")
def top_artists(request: Request):
    """Fetches top artists for the logged-in user"""
    token = request.session.get("spotify_token")  # Assuming you're using session storage
    if not token:
        return {"error": "User not logged in"}
    
    return get_top_artists(token)
