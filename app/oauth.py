import requests, os, time, httpx, aiohttp, base64
from urllib.parse import urlencode
from dotenv import load_dotenv
from app.database import get_db_connection
from app.spotify_api import SpotifyClient
from app.db import User

from fastapi.responses import RedirectResponse, JSONResponse
from fastapi import Request, HTTPException, status, FastAPI, Depends
from fastapi_sessions.backends.implementations import InMemoryBackend
from fastapi_sessions.session_verifier import SessionVerifier
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from starlette.requests import Request
from typing import Optional
from sqlalchemy import text, select
from datetime import datetime, timedelta, timezone



load_dotenv()
app = FastAPI()

# Production-level secret key
SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret")  # fallback only for dev

# Middleware stack
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


class OAuthSettings:
    def __init__(self):
        self.SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
        self.SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
        self.SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
        self.SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/callback")
        self.SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
        self.SCOPES = "user-top-read user-read-recently-played user-read-playback-state"

        client_creds = f"{self.SPOTIFY_CLIENT_ID}:{self.SPOTIFY_CLIENT_SECRET}"
        self.client_credentials_b64 = base64.b64encode(client_creds.encode()).decode()

    def __str__(self):
        return f"OAuthSettings(client_id={self.SPOTIFY_CLIENT_ID}, redirect_uri={self.SPOTIFY_REDIRECT_URI})"


class SpotifyOAuth:
    def __init__(self, settings: OAuthSettings):
        self.settings = settings
        self.client_id = settings.SPOTIFY_CLIENT_ID
        self.client_secret = settings.SPOTIFY_CLIENT_SECRET
        self.redirect_uri = settings.SPOTIFY_REDIRECT_URI

    def get_spotify_login_url(self, request: Request) -> str:
        state = os.urandom(16).hex()
        request.session["spotify_auth_state"] = state  # Save state in session
        params = {
            "client_id": self.settings.SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self.settings.SPOTIFY_REDIRECT_URI,
            "scope": self.settings.SCOPES,
            "state": state
        }
        return f"{self.settings.SPOTIFY_AUTH_URL}?{urlencode(params)}"

    async def get_spotify_token(self, code: str, state: str, request: Request) -> dict:
        # Check that the 'state' matches
        stored_state = request.session.get("spotify_auth_state")
        if not stored_state or stored_state != state:
            raise HTTPException(status_code=400, detail="State mismatch. Possible CSRF attack.")
        
        url = self.settings.SPOTIFY_TOKEN_URL
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.SPOTIFY_REDIRECT_URI,
            "client_id": self.settings.SPOTIFY_CLIENT_ID,
            "client_secret": self.settings.SPOTIFY_CLIENT_SECRET
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, data=payload)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Error fetching access token: {response.text}")
        
        token_info = response.json()
        request.session["spotify_token"] = token_info.get("access_token")
        request.session["refresh_token"] = token_info.get("refresh_token")
        request.session["token_expires"] = time.time() + token_info.get("expires_in", 3600)  # Set expiration time

        return token_info

    def get_valid_token(self, request: Request) -> Optional[str]:
        token = request.session.get("spotify_token")
        refresh_token = request.session.get("refresh_token")
        token_expires = request.session.get("token_expires")

        # Check if the token is valid (not expired)
        if token and token_expires and time.time() < token_expires:
            return token  # Token is still valid

        # If token is expired, try refreshing it using the refresh token
        if refresh_token:
            print("Token expired, attempting to refresh...")
            new_token_data = self.refresh_access_token(refresh_token)
            print("New token data:", new_token_data)
            if new_token_data:
                new_token = new_token_data.get("access_token")
                expires_in = new_token_data.get("expires_in", 3600)  # Default to 3600 seconds if not provided
                request.session["spotify_token"] = new_token
                request.session["token_expires"] = time.time() + expires_in
                print("Token refreshed successfully.")
                return new_token

        print("No valid token available.")
        return None


    async def refresh_access_token(self, refresh_token: str) -> dict:
        print("Starting to refresh access token...")
        url = "https://accounts.spotify.com/api/token"
        headers = {
            "Authorization": f"Basic {self.settings.client_credentials_b64}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        print("got data from API")
        async with aiohttp.ClientSession() as session:
            print("started async session")
            async with session.post(url, headers=headers, data=data) as response:
                print("got response from API:", response.status)
                if response.status != 200:
                    raise Exception(f"Failed to refresh token: {await response.text()}")
                token_data = await response.json()
                
                # ✅ If a new refresh_token is provided by Spotify
                if "refresh_token" in token_data:
                    new_refresh_token = token_data["refresh_token"]
                    print("New refresh token received:", new_refresh_token)
                    await self.update_refresh_token_in_db(old_refresh_token=refresh_token, new_refresh_token=new_refresh_token)

                # Always recalculate expires_at
                token_data["expires_at"] = int(time.time()) + token_data["expires_in"]
                return token_data

    async def update_refresh_token_in_db(self, old_refresh_token: str, new_refresh_token: str):
        print(f"Updating refresh token in DB: {old_refresh_token} -> {new_refresh_token}")
        async with get_db_connection() as session:
            result = await session.execute(
                select(User).where(User.refresh_token == old_refresh_token)
            )
            user = result.scalar_one_or_none()

            if user:
                user.refresh_token = new_refresh_token
                await session.commit()


class SpotifyUser:
    def __init__(self, access_token: str, refresh_token: Optional[str] = None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in = 3600  # Default expiration time in seconds

    def get_user_profile(self) -> dict:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        user_response = requests.get("https://api.spotify.com/v1/me", headers=headers)
        
        if user_response.status_code != 200:
            raise HTTPException(status_code=user_response.status_code, detail="Failed to fetch user data from Spotify")

        return user_response.json()

    async def store_user_info_to_database(self, user_profile: dict, db) -> Optional[dict]:
        if isinstance(user_profile, dict):
            # Extract user profile details
            user_id = user_profile.get("id")
            display_name = user_profile.get("display_name")
            profile_url = user_profile.get("external_urls", {}).get("spotify")
            image_url = user_profile.get("images", [{}])[0].get("url")
            username = user_profile.get("display_name")
            email = user_profile.get("email", "unknown_email@example.com")
            country = user_profile.get("country")
            product = user_profile.get("product")
            followers = str(user_profile.get("followers", {}).get("total", 0))
            external_urls = user_profile.get("external_urls", {}).get("spotify")
            href = user_profile.get("href")
            uri = user_profile.get("uri")
            user_type = user_profile.get("type")

            # Compute token expiry timestamp
            token_expires = datetime.now(timezone.utc) + timedelta(seconds=self.expires_in)

            query = text("""
                INSERT INTO users (user_id, display_name, profile_url, image_url, username, email, country, product, 
                                followers, external_urls, href, uri, type, last_updated, access_token, refresh_token, token_expires) 
                VALUES (:user_id, :display_name, :profile_url, :image_url, :username, :email, :country, :product, 
                        :followers, :external_urls, :href, :uri, :type, NOW(), :access_token, :refresh_token, :token_expires)  
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
                    last_updated = NOW(),
                    access_token = EXCLUDED.access_token,
                    refresh_token = COALESCE(EXCLUDED.refresh_token, users.refresh_token),
                    token_expires = EXCLUDED.token_expires
            """)

            await db.execute(query, {
                "user_id": user_id,
                "display_name": display_name,
                "profile_url": profile_url,
                "image_url": image_url,
                "username": username,
                "email": email,
                "country": country,
                "product": product,
                "followers": followers,
                "external_urls": external_urls,
                "href": href,
                "uri": uri,
                "type": user_type,
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "token_expires": token_expires
            })

            await db.commit()
            return user_profile
        else:
            print("No user data to insert.")
            return None


class SpotifyHandler:
    def __init__(self, oauth_settings: OAuthSettings, spotify_oauth: SpotifyOAuth):
        self.oauth_settings = oauth_settings
        self.spotify_oauth = spotify_oauth

    async def handle_spotify_callback(self, request: Request) -> dict:
        """
        Handles the Spotify OAuth callback, exchanges the code for tokens,
        fetches the user's profile, and stores it in the database.
        """
        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing code or state in callback URL")

        token_info = await self.spotify_oauth.get_spotify_token(code, state, request)

        access_token = token_info.get("access_token")
        refresh_token = token_info.get("refresh_token")
        expires_in = token_info.get("expires_in")

        if not access_token:
            raise HTTPException(status_code=400, detail="No access token returned from Spotify")

        # Initialize Spotify user handler
        user = SpotifyUser(access_token, refresh_token)

        # ✅ Set these values explicitly so store_user_info_to_database can use them
        user.access_token = access_token
        user.refresh_token = refresh_token
        user.expires_in = expires_in

        user_profile = user.get_user_profile()

        # Store user info in database
        db = await get_db_connection()
        await user.store_user_info_to_database(user_profile, db)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user_id": user_profile.get("id"),
            "user_profile": user_profile
        }

    @staticmethod
    async def get_current_user(request: Request) -> dict | RedirectResponse | JSONResponse:
        token = request.session.get("spotify_token")
        user_id = request.session.get("user_id")

        if not token or not user_id:
            return RedirectResponse(url="/login")

        db = await get_db_connection()

        # Retrieve access_token from DB
        stmt = select(User.access_token).where(User.user_id == user_id)
        result = await db.execute(stmt)
        access_token = result.scalar_one_or_none()

        if not access_token:
            return JSONResponse(content={"error": "User not found in DB."}, status_code=404)

        # Optional: Update session with DB value (overwriting old token if needed)
        request.session["spotify_token"] = access_token

        # Use the token to get Spotify profile
        client = SpotifyClient(access_token)
        user_profile = await client.get_spotify_user_profile()

        if not user_profile:
            return JSONResponse(
                content={"error": "Failed to fetch user profile from Spotify."},
                status_code=500
            )

        # Store or update user info in DB
        user_instance = SpotifyUser(access_token)
        user_data = await user_instance.store_user_info_to_database(user_profile, db)

        new_user_id = user_data.get("id") if user_data else None
        if new_user_id and new_user_id != user_id:
            request.session["user_id"] = new_user_id

        return {
            "token": access_token,
            "user_id": request.session["user_id"]
        }













"""
# OAuth-related settings
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
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
                    "
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
                    ", 
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
"""