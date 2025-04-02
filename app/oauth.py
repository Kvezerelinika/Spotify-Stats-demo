import requests, os, time, httpx, json
from urllib.parse import urlencode
from dotenv import load_dotenv
from app.database import get_db_connection
from app.spotify_api import get_spotify_user_profile

from fastapi.responses import RedirectResponse, JSONResponse
from fastapi import Request, HTTPException, status, FastAPI, Depends
from fastapi_sessions.backends.implementations import InMemoryBackend
from fastapi_sessions.session_verifier import SessionVerifier
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from starlette.requests import Request

load_dotenv()
app = FastAPI()

backend = InMemoryBackend()

SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret")
app.add_middleware(
    SessionMiddleware,
    SECRET_KEY="your_secret_key",  # Replace with a strong secret key
    cookie_secure=True,            # Ensure cookies are only sent over HTTPS
    cookie_httponly=True,          # Make cookies inaccessible via JavaScript
    cookie_samesite="None"         # Allow cookies in cross-site requests (for OAuth)
)

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")  # Make sure this is set in .env
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/callback")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SCOPES = "user-top-read user-read-recently-played user-read-playback-state"



def get_spotify_login_url(request: Request):
    state = os.urandom(16).hex()
    request.session["spotify_auth_state"] = state  # Save state in session
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": SCOPES,
        "state": state
    }
    return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"


async def get_spotify_token(code: str, state: str, request: Request):
    # Check that the 'state' matches
    stored_state = request.session.get("spotify_auth_state")
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="State mismatch. Possible CSRF attack.")
    
    url = "https://accounts.spotify.com/api/token"
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

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, data=payload)
    
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Error fetching access token: {response.text}")
    
    # Process the response
    token_info = response.json()
    request.session["spotify_token"] = token_info.get("access_token")
    request.session["refresh_token"] = token_info.get("refresh_token")
    request.session["token_expires"] = time.time() + token_info.get("expires_in", 3600)  # Set expiration time

    return token_info

def refresh_access_token(refresh_token: str):
    url = "https://accounts.spotify.com/api/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET
    }

    try:
        response = requests.post(url, data=data)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx, 5xx)

        new_token_data = response.json()

        # Check if the 'access_token' is in the response data
        if "access_token" in new_token_data:
            access_token = new_token_data["access_token"]
            expires_in = new_token_data.get("expires_in", 3600)  # Default to 3600 seconds if not provided
            return access_token, expires_in
        
        # If 'access_token' is not in the response, print the error message
        print("Error refreshing token: Missing 'access_token' in response.", new_token_data)
        return None, None

    except requests.exceptions.RequestException as e:
        # Catch any exception raised by requests (network issues, invalid response, etc.)
        print(f"Error refreshing token: {e}")
        return None, None

def get_valid_token(request: Request):
    token = request.session.get("spotify_token")
    refresh_token = request.session.get("refresh_token")
    token_expires = request.session.get("token_expires")

    # Check if the token is valid (not expired)
    if token and token_expires and time.time() < token_expires:
        return token  # Token is still valid

    # If token is expired, try refreshing it using the refresh token
    if refresh_token:
        print("Token expired, attempting to refresh...")
        new_token, expires_in = refresh_access_token(refresh_token)
        if new_token:
            # Save the new token and its expiration time in the session
            request.session["spotify_token"] = new_token
            request.session["token_expires"] = time.time() + expires_in
            print("Token refreshed successfully.")
            return new_token

    # If no valid token or refresh token is available, return None
    print("No valid token available.")
    return None

def handle_spotify_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return {"error": "Authorization failed"}

    # Step 1: Get the access token
    token_info = get_spotify_token(code)

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
    



async def user_info_to_database(user_profile):
    db = await get_db_connection()  # Use asyncpg connection
    if db is None:
        print("Database connection failed. Check get_db_connection()!")
        return None

    try:
        info_users = []
        if isinstance(user_profile, dict):
            # Extract user profile details
            user_id = user_profile.get("id")  # Corrected from 'id'
            display_name = user_profile.get("display_name")
            profile_url = user_profile.get("external_urls", {}).get("spotify")
            image_url = user_profile.get("images", [{}])[0].get("url")  # First image URL if exists
            username = user_profile.get("display_name")  # Spotify doesn't provide a separate username
            email = user_profile.get("email", "unknown_email@example.com")
            country = user_profile.get("country")
            product = user_profile.get("product")
            followers = str(user_profile.get("followers", {}).get("total", 0))  # Convert to string
            external_urls = user_profile.get("external_urls", {}).get("spotify")
            href = user_profile.get("href")
            uri = user_profile.get("uri")
            user_type = user_profile.get("type")

            info_users.append(
                (user_id, display_name, profile_url, image_url, username, email, country, product, 
                 followers, external_urls, href, uri, user_type)
            )

            if info_users:
                print("User Info to Insert: ", info_users)

                # Insert or update user info in the database
                await db.executemany(
                    """
                    INSERT INTO users (user_id, display_name, profile_url, image_url, username, email, country, product, 
                                       followers, external_urls, href, uri, type, last_updated) 
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())  
                    ON CONFLICT (user_id) DO UPDATE 
                    SET display_name = EXCLUDED.display_name, 
                        profile_url = EXCLUDED.profile_url,
                        image_url = EXCLUDED.image_url,
                        username = EXCLUDED.username, 
                        email = EXCLUDED.email, 
                        country = EXCLUDED.country, 
                        product = EXCLUDED.product, 
                        followers = EXCLUDED.followers, 
                        external_urls = EXCLUDED.external_urls, 
                        href = EXCLUDED.href, 
                        uri = EXCLUDED.uri, 
                        type = EXCLUDED.type, 
                        last_updated = NOW()
                    """, 
                    info_users
                )
                return info_users
            else:
                print("No user data to insert.")
                return None

    except Exception as e:
        print(f"Database insertion error: {e}")
        return None
    
    finally:
        await db.close()  # Close the connection asynchronously




async def get_current_user(request: Request):
    token = request.session.get("spotify_token")
    user_id = request.session.get("user_id")

    if not token or not user_id:
        return RedirectResponse(url="/login")

    user_profile = await get_spotify_user_profile(token)
    if not user_profile:
        return JSONResponse(content={"error": "Failed to fetch user profile from Spotify."}, status_code=500)

    user_data = await user_info_to_database(user_profile)
    if user_data:
        new_user_id = user_data[0][0]
        if new_user_id != user_id:
            request.session["user_id"] = new_user_id
            user_id = new_user_id  # Update user_id for further use

    return {"token": token, "user_id": user_id}