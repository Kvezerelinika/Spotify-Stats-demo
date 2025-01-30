from fastapi import FastAPI, Depends
from app.oauth import get_spotify_token
from app.spotify_api import get_top_artists

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Welcome to Spotify Stats API!"}

@app.get("/login")
def login():
    # Redirects user to Spotify login URL
    return get_spotify_token()

@app.get("/api/top-artists")
def top_artists(token: str = Depends(get_spotify_token)):
    # Fetches top artists for the user
    return get_top_artists(token)
