import asyncio, httpx
from fastapi import HTTPException

SPOTIFY_API_URL = "https://api.spotify.com/v1"

async def fetch_spotify_data(url: str, token: str, retries: int = 5, method_name: str = ""):  # Added method_name
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        for attempt in range(retries):
            response = await client.get(url, headers=headers)
            
            if response.status_code == 429:  # Rate limit hit
                retry_after = int(response.headers.get('Retry-After', 2))  # Default to 2s if missing
                print(f"Rate limit hit in {method_name}. Retrying after {retry_after} seconds...")
                await asyncio.sleep(retry_after)
            elif response.status_code == 200:
                json_response = await response.json()
                print(f"{method_name} - JSON Response:", json_response)  # Debugging line
                return await response.json()
            else:
                raise HTTPException(status_code=response.status_code, detail=f"Error in {method_name}: {response.text}")
    raise HTTPException(status_code=500, detail=f"Failed in {method_name} after multiple attempts.")


async def get_top_artists(token: str, time_range: str):
    """Fetch user's top artists for a given time range."""
    if time_range not in ["long_term", "medium_term", "short_term"]:
        raise ValueError("Invalid time range")

    url = f"{SPOTIFY_API_URL}/me/top/artists?time_range={time_range}&limit=50"
    return await fetch_spotify_data(url, token, method_name=f"get_top_artists_{time_range}")


async def get_recently_played_tracks(token: str):
    url = f"{SPOTIFY_API_URL}/me/player/recently-played?limit=50"
    return await fetch_spotify_data(url, token, method_name="get_recently_played_tracks")


async def get_top_tracks(token: str):
    url = f"{SPOTIFY_API_URL}/me/top/tracks?time_range=long_term&limit=50"
    return await fetch_spotify_data(url, token, method_name="get_top_tracks")


def get_all_artists(token: str, artist_id: str):
    url = f"{SPOTIFY_API_URL}/artists/{artist_id}"
    response = httpx.get(url, headers={"Authorization": f"Bearer {token}"})
    return response.json() if response.status_code == 200 else {"error in get_all_artists": response.text}


def get_all_albums(token: str, album_id: str):
    url = f"{SPOTIFY_API_URL}/albums/{album_id}"
    response = httpx.get(url, headers={"Authorization": f"Bearer {token}"})
    return response.json() if response.status_code == 200 else {"error in get_all_albums": response.text}


def get_track(token: str, track_ids: list):
    batch_size = 50  # Max 50 track IDs per request
    all_tracks = []
    
    for i in range(0, len(track_ids), batch_size):
        batch = [track.replace("spotify:track:", "") for track in track_ids[i : i + batch_size]]
        url = f"{SPOTIFY_API_URL}/tracks?ids={','.join(batch)}"
        response = httpx.get(url, headers={"Authorization": f"Bearer {token}"})
        
        if response.status_code == 200:
            all_tracks.extend(response.json().get("tracks", []))
        elif response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 2))
            print(f"Rate limit hit in get_track. Retrying after {retry_after} seconds...")
            asyncio.sleep(retry_after)
        else:
            print(f"Error fetching batch in get_track: {response.text}")
    
    return all_tracks


async def get_spotify_user_profile(token: str):
    url = f"{SPOTIFY_API_URL}/me"
    return await fetch_spotify_data(url, token, method_name="get_spotify_user_profile")


async def get_now_playing(token: str):
    url = f"{SPOTIFY_API_URL}/me/player/currently-playing"
    data = await fetch_spotify_data(url, token, method_name="get_now_playing")
    
    # Check if there is currently a track playing
    if data.get('is_playing', False):
        track_name = data['item']['name']
        artists = [artist['name'] for artist in data['item']['artists']]
        artist_names = ", ".join(artists)
        
        # Get the album image (usually the first one in the list is the highest resolution)
        album_image_url = data['item']['album']['images'][0]['url'] if data['item']['album']['images'] else None
        
        return {
            "track_name": track_name,
            "artists": artist_names,
            "album_image_url": album_image_url
        }
    else:
        return {
            "track_name": None,
            "artists": None,
            "album_image_url": None
        }
