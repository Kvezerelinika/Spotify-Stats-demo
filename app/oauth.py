import requests
import os
from fastapi.responses import RedirectResponse
from fastapi import Request
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")  # Make sure this is set in .env
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8000/callback" # Correctly loaded from .env
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SCOPES = "user-top-read user-read-recently-played"

def get_spotify_token():
    auth_url = f"https://accounts.spotify.com/authorize?client_id={SPOTIFY_CLIENT_ID}&response_type=code&redirect_uri={SPOTIFY_REDIRECT_URI}&scope={SCOPES}"
    return auth_url

def exchange_code_for_token(code: str):
    response = requests.post(SPOTIFY_TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET
    })
    return response.json()

def handle_spotify_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return {"error": "Authorization failed"}

    token_url = "https://accounts.spotify.com/api/token"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(token_url, data=data, headers=headers)
    token_info = response.json()

    if "access_token" in token_info:
        return {"access_token": token_info["access_token"]}
    else:
        return {"error": "Failed to get access token"}
    
def get_spotify_login_url():
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": SCOPES
    }
    return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str):
    token_url = "https://accounts.spotify.com/api/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET
    }
    response = requests.post(token_url, headers=headers, data=payload)
    
    if response.status_code != 200:
        raise Exception(f"Error fetching access token: {response.status_code}, {response.text}")
    
    return response.json()