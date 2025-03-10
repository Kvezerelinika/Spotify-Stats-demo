import requests, httpx
from fastapi import HTTPException

SPOTIFY_API_URL = "https://api.spotify.com/v1"

async def get_top_artists(token):
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://api.spotify.com/v1/me/top/artists?time_range=long_term&limit=50"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Error fetching recently top artists: {response.text}")
    
    return response.json()

async def get_recently_played_tracks(token: str):
    url = "https://api.spotify.com/v1/me/player/recently-played?limit=50"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Error fetching recently played tracks: {response.text}")
    
    return response.json()

async def get_top_tracks(token: str):
    url = "https://api.spotify.com/v1/me/top/tracks?time_range=long_term&limit=50"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Error fetching top tracks: {response.text}")
    
    return response.json()



def get_all_artists(token: str, id: str):
    url = f"https://api.spotify.com/v1/artists/{id}"  # Use f-string to insert `id` value
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    return {"error": response.json()}


def get_all_albums(token: str, id):
    url = "https://api.spotify.com/v1/albums/{id}"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    return {"error": response.json()}


import time
import requests
from app.database import get_db_connection

def get_track(token, track_ids):
    batch_size = 50  # Max 50 track IDs per request
    all_tracks = []

    for i in range(0, len(track_ids), batch_size):
        batch = track_ids[i : i + batch_size]  # ✅ Correctly slicing track_ids

        # Remove "spotify:track:" prefix if present
        batch = [track_id.replace("spotify:track:", "") for track_id in batch]

        # Print batch to verify track IDs
        print(f"Batch {i}-{i+batch_size}: {batch}")

        url = f"https://api.spotify.com/v1/tracks?ids={','.join(batch)}"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(url, headers=headers)

        print(f"Fetching {len(batch)} tracks... Status Code from get_tracks: {response.status_code}")

        if response.status_code == 200:
            all_tracks.extend(response.json().get("tracks", []))
        else:
            print(f"Error fetching batch from get_tracks {i}-{i+batch_size}: {response.status_code}")
            print("Response:", response.text)  # Print API response for debugging

        time.sleep(2)  # Prevent hitting rate limits

    return all_tracks









def get_spotify_user_profile(token):
    url = "https://api.spotify.com/v1/me"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()  # Ensure it returns a valid JSON response with user data
    else:
        print("Error fetching user profile:", response.text)
        return None
