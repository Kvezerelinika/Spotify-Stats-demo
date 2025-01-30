import requests

SPOTIFY_API_URL = "https://api.spotify.com/v1"

def get_top_artists(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{SPOTIFY_API_URL}/me/top/artists", headers=headers)
    if response.status_code == 200:
        return response.json()
    return {"error": response.json()}
