import requests

SPOTIFY_API_URL = "https://api.spotify.com/v1"

def get_top_artists(token):
    headers = {
        "Authorization": f"Bearer {token}"
    }
    url = "https://api.spotify.com/v1/me/top/artists"
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data from Spotify. Status code: {response.status_code}")
    
    return response.json()

