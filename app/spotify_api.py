import asyncio, httpx
from fastapi import HTTPException
from typing import List


SPOTIFY_API_URL = "https://api.spotify.com/v1"


class SpotifyClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": f"Bearer {self.token}"}

    async def _fetch_spotify_data(self, url: str, retries: int = 5, method_name: str = ""):
        async with httpx.AsyncClient() as client:
            for attempt in range(retries):
                response = await client.get(url, headers=self.headers)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 30))
                    print(f"Rate limit hit in {method_name}. Retrying after {retry_after} seconds...")
                    await asyncio.sleep(retry_after)
                elif 500 <= response.status_code < 600:
                    print(f"Server error in {method_name}. Retrying...")
                    await asyncio.sleep(2 ** attempt)
                elif response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as e:
                        print(f"Error decoding JSON in {method_name}: {e}")
                        raise HTTPException(status_code=500, detail=f"Error decoding JSON in {method_name}")
                elif response.status_code == 204:
                    print(f"{method_name} - No content.")
                    return None
                else:
                    raise HTTPException(status_code=response.status_code, detail=f"Error in {method_name}: {response.text}")
        raise HTTPException(status_code=500, detail=f"Failed in {method_name} after multiple attempts.")
    

    async def get_top_artists(self, time_range: str = "medium_term"):
        """Fetch user's top artists for a given time range."""
        if time_range not in ["long_term", "medium_term", "short_term"]:
            raise ValueError("Invalid time range")

        # Construct the URL
        url = f"{SPOTIFY_API_URL}/me/top/artists?time_range={time_range}&limit=50"
        
        # Log the URL being used
        print("URL in get_top_artists: ", url)
        
        # Fetch data from Spotify API
        return await self._fetch_spotify_data(url, method_name=f"get_top_artists_{time_range}")



    async def get_recently_played_tracks(self):
        # Construct the URL for recently played tracks
        url = f"{SPOTIFY_API_URL}/me/player/recently-played?limit=50"
        
        # Log the URL being used
        print("URL in get_recently_played_tracks: ", url)
        
        # Fetch data from Spotify API
        response = await self._fetch_spotify_data(url, method_name="get_recently_played_tracks")
        
        # Check if the response is valid and contains the 'items' key
        if response and isinstance(response, dict) and "items" in response:
            return response["items"]  # Return the list of tracks
        else:
            print("No recent tracks found or invalid response format.")
            return []


    async def get_top_tracks(self, time_range: str):
        """Fetch user's top tracks for a given time range."""
        if time_range not in ["long_term", "medium_term", "short_term"]:
            raise ValueError("Invalid time range")
        
        # Construct the URL
        url = f"{SPOTIFY_API_URL}/me/top/tracks?time_range={time_range}&limit=50"
        
        # Log the URL being used
        print("URL in get_top_tracks: ", url)
        
        # Fetch data from Spotify API
        return await self._fetch_spotify_data(url, method_name=f"get_top_tracks_{time_range}")


    async def get_all_artists(self, artist_id: List[str]):
        url = f"{SPOTIFY_API_URL}/artists?ids={','.join(artist_id)}"

        return await self._fetch_spotify_data(url, method_name="get_all_artists")


    async def get_all_albums(self, album_id: List[str]):
        url = f"{SPOTIFY_API_URL}/albums?ids={','.join(album_id)}"
        
        return await self._fetch_spotify_data(url, method_name="get_all_albums")



    async def get_track(self, track_ids: List[str]):
        print("Starting to get_tracks from spotify_api.py")
        url = f"{SPOTIFY_API_URL}/tracks?ids={','.join(track_ids)}"
        
        try:
            response = await self._fetch_spotify_data(url, method_name="get_track")
            return response
        except Exception as e:
            print(f"[get_track ERROR] Failed to fetch track data: {e}")
            raise  # or return None





    async def get_spotify_user_profile(self):
        url = f"{SPOTIFY_API_URL}/me"
        return await self._fetch_spotify_data(url, method_name="get_spotify_user_profile")


    async def get_now_playing(self):
        url = f"{SPOTIFY_API_URL}/me/player/currently-playing"
        data = await self._fetch_spotify_data(url, method_name="get_now_playing")
        
        if data is None or not data.get('is_playing', False):
            # No track is currently playing
            return {
                "track_name": None,
                "artists": None,
                "album_image_url": None
            }

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