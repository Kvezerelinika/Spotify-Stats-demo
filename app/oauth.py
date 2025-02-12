import requests
import os
from fastapi.responses import RedirectResponse
from fastapi import Request
from urllib.parse import urlencode
from dotenv import load_dotenv
from fastapi import Request, HTTPException, status
from app.database import get_db_connection

load_dotenv()

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")  # Make sure this is set in .env
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8000/callback" # Correctly loaded from .env
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SCOPES = "user-top-read user-read-recently-played"

def get_spotify_token(request: Request):
    return request.session.get("spotify_token")

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

    # Step 1: Get the access token
    token_info = exchange_code_for_token(code)

    if "access_token" not in token_info:
        return {"error": "Failed to get access token"}

    access_token = token_info["access_token"]

    # Step 2: Fetch user data (including user ID) using the access token
    headers = {"Authorization": f"Bearer {access_token}"}
    user_response = requests.get("https://api.spotify.com/v1/me", headers=headers)
    
    if user_response.status_code != 200:
        raise HTTPException(status_code=user_response.status_code, detail="Failed to fetch user data from Spotify")

    # Parse the user data
    user_data = user_response.json()

    # Get the user ID from the response
    spotify_user_id = user_data["id"]  # Spotify's user ID
    print(f"\n Spotify User ID: {spotify_user_id} \n")
    
    # You can also get additional details, like the user's display name
    display_name = user_data.get("display_name", "Unknown")

    # Step 3: Store the user ID and token in the session (or wherever you need it)
    request.session["user_id"] = spotify_user_id  # Store Spotify User ID
    request.session["access_token"] = access_token  # Optionally store the token for future requests

    return {
        "user_id": spotify_user_id,
        "display_name": display_name,
        "access_token": access_token
    }
    
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


def get_user_id_from_session(request: Request):

    user_id = request.session.get("user_id")  # Assuming you're using session for user authentication
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user_id


def user_info_to_database(user_profile):
    db = get_db_connection()
    cursor = db.cursor()

    try:
        info_users = []
        if isinstance(user_profile, dict):  # Check if the data is a dictionary
            id = user_profile.get("id")
            username = user_profile.get("display_name")
            email = user_profile.get("email")

            info_users.append((id, username, email))

            if info_users:
                print("User Info to Insert: ", info_users)  # Debugging before inserting into DB
                cursor.executemany(
                    "INSERT INTO users (id, username, email) VALUES (%s, %s, %s)  "
                    "ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, username = EXCLUDED.username", 
                    info_users
                )
            else: 
                print("No user data to insert.")
            db.commit()
        else:
            print("Error: user_profile is not a dictionary")

    except Exception as e:
        print(f"Database insertion error: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()

