import requests

SPOTIFY_API_URL = "https://api.spotify.com/v1"

def get_top_artists(token):
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://api.spotify.com/v1/me/top/artists?time_range=long_term&limit=50"
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data from Spotify. Status code: {response.status_code}")
    
    return response.json()

def get_recently_played_tracks(token: str):
    url = "https://api.spotify.com/v1/me/player/recently-played?limit=50"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    return {"error": response.json()}

def get_top_tracks(token: str):
    url = "https://api.spotify.com/v1/me/top/tracks?time_range=long_term&limit=50"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    return {"error": response.json()}


def get_all_artists(token: str, id):
    url = "https://api.spotify.com/v1/artists/{id}"
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

def get_spotify_user_profile(token):
    url = "https://api.spotify.com/v1/me"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()  # Ensure it returns a valid JSON response with user data
    else:
        print("Error fetching user profile:", response.text)
        return None
