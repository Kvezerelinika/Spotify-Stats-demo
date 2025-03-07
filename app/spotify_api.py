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


import requests

def get_track(token, track_ids):
    url = f"https://api.spotify.com/v1/tracks/{track_ids}"  # Make sure to request the track data properly
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)

    print(f"Status Code: {response.status_code}")  # Print status code for debugging
    print(f"Response Text: {response.text}")  # Print raw response before calling .json()

    if response.status_code == 200:
        return response.json()  # Assuming the response is a dictionary with track info
    else:
        print(f"Error fetching track {track_ids}: {response.status_code}")
        return []  # Return an empty list on error




def get_spotify_user_profile(token):
    url = "https://api.spotify.com/v1/me"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()  # Ensure it returns a valid JSON response with user data
    else:
        print("Error fetching user profile:", response.text)
        return None
