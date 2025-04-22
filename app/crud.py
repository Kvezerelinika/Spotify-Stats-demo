from app.database import get_db_connection
from app.spotify_api import SpotifyClient
import json, time
from datetime import datetime, timedelta


class SpotifyDataSaver:
    def __init__(self, token: str, user_id: str):
        self.token = token
        self.user_id = user_id
        self.db = None

    async def connect_db(self):
        self.db = await get_db_connection()

    async def close_db(self):
        if self.db:
            await self.db.close()  # or .disconnect(), depending on your DB driver

    async def __aenter__(self):
        await self.connect_db()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close_db()



    async def top_artists_to_database(self, top_artists: dict, time_range: str, current_time: datetime):
        "Saves user's top artists to database"

        try:
            existing_artist_query = "SELECT artist_id FROM artists;"
            existing_artists_result = await self.db.fetch(existing_artist_query)
            existing_artist_ids = {row["artist_id"] for row in existing_artists_result}

            new_artist_ids = [artist["id"] for artist in top_artists["items"] if artist["id"] not in existing_artist_ids]

            if new_artist_ids:
                await self.update_artist_details(new_artist_ids)

                existing_artists_result = await self.db.fetch(existing_artist_query)
                existing_artist_ids = {row ["artist_id"] for row in existing_artists_result}

            delete_query = "DELETE FROM users_top_artists WHERE user_id = $1 AND time_range = $2;"
            
            await self.db.execute(delete_query, self.user_id, time_range)

            top_artist_records = [
                (
                    self.user_id,
                    artist["id"],
                    index + 1,
                    time_range,
                    current_time
                )
                for index, artist in enumerate(top_artists["items"])
                if artist["id"] in existing_artist_ids
            ]

            if top_artist_records:
                insert_query = """
                    INSERT INTO users_top_artists (user_id, artist_id, rank, time_range, last_updated) VALUES ($1, $2, $3, $4, $5);"""
                
                await self.db.executemany(insert_query, top_artist_records)
                print("Top artists data inserted successfully.")

        except Exception as e:
            print(f"[error] save_top_artists: {e}")



    async def update_artist_details(self, artist_ids: list[str]):
        "Updates the artists table with the given artist details in batches of 50."
        print("Enriching artist details in the database...")
        if not self.db:
            raise Exception("Database connection not initialized. Call connect_db() first.")

        try:
            artist_updates = []

            # Process artist_ids in batches of 50
            for i in range(0, len(artist_ids), 50):
                batch_artist_ids = artist_ids[i:i+50]  # Select a batch of 50 artist IDs
                
                try:
                    # Fetch all artist details in one request
                    artists_data = await SpotifyClient.get_all_artists(self.token, batch_artist_ids)
                    artists_list = artists_data.get("artists", [])  # Extract artist details list

                    for artist_details in artists_list:
                        artist_id = artist_details["id"]
                        artist_name = artist_details["name"]
                        genres = list(artist_details.get("genres", []))  # Convert genres to a list
                        if not genres:
                            genres = None  # Handle empty genres properly
                        image_url = artist_details["images"][0]["url"] if artist_details.get("images") else None
                        spotify_url = artist_details["external_urls"]["spotify"]
                        followers = artist_details["followers"]["total"]
                        popularity = artist_details["popularity"]
                        uri = artist_details["uri"]

                        # Prepare the artist data for the update
                        artist_updates.append((
                            artist_id, artist_name, genres, image_url, spotify_url, followers, popularity, uri
                        ))

                except Exception as e:
                    print(f"Failed to get artist details for batch {batch_artist_ids}: {e}")
                    continue  # Skip to the next batch

                # After processing a batch, update the database
                if artist_updates:
                    insert_or_update_query = """
                        INSERT INTO artists (artist_id, name, genres, image_url, spotify_url, followers, popularity, uri)
                        VALUES ($1, $2, $3::TEXT[], $4, $5, $6, $7, $8)
                        ON CONFLICT (artist_id)
                        DO UPDATE SET
                            name = EXCLUDED.name,
                            genres = EXCLUDED.genres,
                            image_url = EXCLUDED.image_url,
                            spotify_url = EXCLUDED.spotify_url,
                            followers = EXCLUDED.followers,
                            popularity = EXCLUDED.popularity,
                            uri = EXCLUDED.uri
                    """

                    async with self.db.transaction():
                        await self.db.executemany(insert_or_update_query, artist_updates)

                    # Reset artist_updates for the next batch
                    artist_updates = []

            if not artist_ids:
                print("No artist data to enrich.")

        except Exception as e:
            print(f"Database insertion error in update_artist_details: {e}")




    async def top_tracks_to_database(self, top_tracks: dict, time_range: str):
        print("Inserting top tracks data into the database...")

        try:
            # Step 1: Delete existing top tracks for this user and time range
            async with self.db.transaction():  
                delete_existing_data_query = """
                    DELETE FROM users_top_tracks WHERE user_id = $1 AND time_range = $2;
                """
                await self.db.execute(delete_existing_data_query, self.user_id, time_range)

            # Step 2: Prepare new top tracks data
            top_records = []
            top_track_ids = set()

            for index, track in enumerate(top_tracks["items"]):
                track_id = track["id"]
                rank = index + 1  # Rank is based on the index (1-based)

                # Save only essential information
                top_records.append((self.user_id, track_id, rank, time_range, datetime.now().date()))
                top_track_ids.add(track_id)

            # Step 3: Ensure tracks exist in the tracks table
            if top_track_ids:
                await self.update_tracks_details(list(top_track_ids))  # Convert set to list

            # Step 4: Insert new top tracks data
            if top_records:
                async with self.db.transaction():  # ✅ Ensure atomic insertion
                    query = """
                        INSERT INTO users_top_tracks 
                        (user_id, track_id, rank, time_range, last_updated) 
                        VALUES ($1, $2, $3, $4, $5);
                    """
                    await self.db.executemany(query, top_records)

            else:
                print("No top tracks to insert.")

        except Exception as e:
            print(f"Database insertion error in crud.py top_tracks_to_database: {e}")



    async def update_tracks_details(self, track_ids):
        print("Enriching tracks database with new track details...")
        if not self.db:
            raise Exception("Database connection not initialized. Call connect_db() first.")

        try:
            track_updates = []
            track_artist_relationships = []  # List to store track-artist relationships
            artists_id_to_add = set()
            album_ids_to_add = set()

            # Split the track_ids into batches of 50
            batch_size = 50
            track_id_batches = [track_ids[i:i + batch_size] for i in range(0, len(track_ids), batch_size)]

            for batch in track_id_batches:
                try:
                    # Fetch the details for the current batch of tracks
                    tracks_details = await SpotifyClient.get_track(self.token, batch)

                    for track_details in tracks_details.get("tracks", []):
                        if not track_details:
                            continue  # Skip if track details are missing

                        track_id = track_details.get("id")
                        track_name = track_details.get("name", "Unknown")
                        
                        # Collect artist IDs and names
                        artist_ids = [artist.get("id", "Unknown") for artist in track_details.get("artists", [])]
                        artist_names = [artist.get("name", "Unknown") for artist in track_details.get("artists", [])]
                        
                        # Collect album details
                        album_details = track_details.get("album", {})
                        album_id = album_details.get("id", "Unknown")
                        album_name = album_details.get("name", "Unknown")
                        
                        # Select highest resolution album image
                        album_image_url = next((img["url"] for img in album_details.get("images", []) if img["height"] == 640), None)
                        if not album_image_url and album_details.get("images"):  # Fallback
                            album_image_url = album_details["images"][0]["url"]

                        release_date_str = album_details.get("release_date", None)
                        release_date = self.parse_release_date(release_date_str)

                        duration_ms = track_details.get("duration_ms", 0)
                        is_explicit = track_details.get("explicit", False)
                        spotify_url = track_details["external_urls"].get("spotify", "") if track_details.get("external_urls") else ""
                        popularity = track_details.get("popularity", 0)
                        track_number = track_details.get("track_number", 0)

                        # Add to artist and album sets
                        artists_id_to_add.update(artist_ids)
                        album_ids_to_add.add(album_id)

                        # Prepare track update data
                        track_updates.append((
                            track_id, track_name, album_id, artist_ids[0] if artist_ids else None,  
                            spotify_url, duration_ms, popularity, is_explicit, track_number,
                            release_date, album_image_url, album_name, artist_names[0] if artist_names else None
                        ))

                        # Prepare track-artist relationships
                        for artist_id in artist_ids:
                            track_artist_relationships.append((track_id, artist_id))

                except Exception as batch_error:
                    print(f"Error fetching details for batch {batch}: {batch_error}")
                    continue

            # Process all artists first
            if artists_id_to_add:
                await self.update_artist_details(list(artists_id_to_add))

            # Process albums after artists
            if album_ids_to_add:
                await self.all_albums_to_database(list(album_ids_to_add))

            # Insert tracks last
            if track_updates:
                print("Inserting/updating track details into the database...")
                insert_or_update_query = """
                    INSERT INTO tracks (
                        track_id, name, album_id, artist_id, spotify_url, duration_ms, popularity, 
                        explicit, track_number, album_release_date, album_image_url, album_name, artist_name
                    ) 
                    VALUES 
                        ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (track_id) 
                    DO UPDATE SET
                        name = COALESCE(EXCLUDED.name, tracks.name),
                        album_id = COALESCE(EXCLUDED.album_id, tracks.album_id),
                        artist_id = CASE 
                            WHEN tracks.artist_id IS NULL THEN EXCLUDED.artist_id
                            ELSE tracks.artist_id
                        END,
                        artist_name = CASE 
                            WHEN tracks.artist_name IS NULL THEN EXCLUDED.artist_name
                            ELSE tracks.artist_name
                        END,
                        spotify_url = COALESCE(EXCLUDED.spotify_url, tracks.spotify_url),
                        duration_ms = COALESCE(EXCLUDED.duration_ms, tracks.duration_ms),
                        popularity = COALESCE(EXCLUDED.popularity, tracks.popularity),
                        explicit = COALESCE(EXCLUDED.explicit, tracks.explicit),
                        track_number = COALESCE(EXCLUDED.track_number, tracks.track_number),
                        album_release_date = COALESCE(EXCLUDED.album_release_date, tracks.album_release_date),
                        album_image_url = COALESCE(EXCLUDED.album_image_url, tracks.album_image_url),
                        album_name = COALESCE(EXCLUDED.album_name, tracks.album_name)
                """

                async with self.db.transaction():
                    print("Executing batch insert/update for tracks...")
                    await self.db.executemany(insert_or_update_query, track_updates)
                    print("Track details inserted/updated successfully.")

            # Insert track-artist relationships
            if track_artist_relationships:
                print("Inserting track-artist relationships into the database...")
                insert_track_artist_query = """
                    INSERT INTO track_artists (track_id, artist_id)
                    VALUES ($1, $2)
                    ON CONFLICT (track_id, artist_id) DO NOTHING
                """

                async with self.db.transaction():
                    await self.db.executemany(insert_track_artist_query, track_artist_relationships)
                    print("Track-artist relationships inserted successfully.")

            else:
                print("No tracks to enrich for update_tracks_details.")

            # If some artist_names were missing, re-call the update function
            await self.retry_update_tracks_if_needed()

        except Exception as e:
            print(f"Error enriching tracks database in crud.py for update_tracks_details: {e}")



    async def retry_update_tracks_if_needed(self):
        # Check for missing artist names in the tracks table
        missing_artist_names_query = """
            SELECT track_id FROM tracks WHERE artist_name IS NULL OR artist_name = 'Unknown'
        """
        result = await self.db.fetch(missing_artist_names_query)

        if result:  # If there are any tracks with missing artist names
            missing_track_ids = [row['track_id'] for row in result]
            print(f"Retrying update for tracks with missing artist names: {missing_track_ids}")
            await self.update_tracks_details(missing_track_ids, self.token)  # Recall the update function


    def parse_release_date(release_date_str):
        """Parses Spotify's release date format correctly, even if it's only a year or year-month format."""
        if not release_date_str:
            return None  # Handle missing values gracefully

        try:
            if len(release_date_str) == 4:  # Only year provided (e.g., "2008")
                return datetime.strptime(release_date_str, "%Y").date()
            elif len(release_date_str) == 7:  # Year and month provided (e.g., "2008-06")
                return datetime.strptime(release_date_str, "%Y-%m").date()
            else:  # Full date (e.g., "2008-06-15")
                return datetime.strptime(release_date_str, "%Y-%m-%d").date()
        except ValueError as e:
            print(f"Error parsing release date '{release_date_str}': {e}")
            return None  # Return None if there's an unexpected format




    async def recents_to_database(self, recent_tracks):
        """Stores user's recent listening history in the database."""

        if not recent_tracks:
            print("No recent tracks to process.")
            return

        track_id_to_add = set()

        # Ensure recent_tracks is a list of dictionaries
        if isinstance(recent_tracks, str):  
            try:
                recent_tracks = json.loads(recent_tracks)  # Convert to Python list
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON: {e}")
                return

        if not isinstance(recent_tracks, list) or not all(isinstance(track, dict) for track in recent_tracks):
            print(f"Invalid format for recent_tracks: {type(recent_tracks)}")
            return

        # Collect all track IDs from the recent tracks
        track_ids = {track["track"]["id"] for track in recent_tracks if "track" in track and "id" in track["track"]}

        # Ensure you await the connection
        try:
            # Start a transaction explicitly
            async with self.db.transaction():
                # First, update track details for the tracks being added
                if track_ids:
                    print("FROM RECENT TO TRACKS UPDATE IDS: ", track_ids)
                    await self.update_tracks_details(list(track_ids))

                # Prepare the insert query
                insert_query = """
                INSERT INTO listening_history (user_id, track_id, played_at)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, track_id, played_at) DO NOTHING;
                """

                # Loop through recent tracks
                for track in recent_tracks:
                    track_data = track.get("track")
                    if track_data and "id" in track_data and "played_at" in track:
                        track_id = track_data["id"]

                        # Add the track ID to the set of IDs to add
                        track_id_to_add.add(track_id)

                        # Convert played_at string to a datetime object
                        played_at_str = track["played_at"]
                        try:
                            played_at = datetime.fromisoformat(played_at_str.replace('Z', '+00:00'))  # Convert to datetime object
                            played_at = played_at.replace(tzinfo=None)  # Remove timezone to make it naive
                        except ValueError as e:
                            print(f"Error parsing datetime: {e}")
                            continue  # Skip this track if the datetime format is incorrect

                        # Insert into the database
                        await self.db.execute(insert_query, self.user_id, track_id, played_at)

            # If track_ids exist, update track details again (if needed)
            if track_ids:
                await self.update_tracks_details(list(track_ids))  # Ensure this function is async

        except Exception as e:
            print(f"Database insertion error in recents_to_database: {e}")


    async def all_albums_to_database(self, album_ids):
        print("Inserting album details into the database...")        
        try:
            async with self.db.transaction():
                tot_albums = []
                new_artists = set()

                # Split album_ids into chunks of 20 (Spotify API limit)
                album_chunks = [album_ids[i:i + 20] for i in range(0, len(album_ids), 20)]

                for chunk in album_chunks:
                    # Fetch album details for the batch
                    album_details_response = await SpotifyClient.get_all_albums(self.token, chunk)
                    
                    if "albums" not in album_details_response:
                        print(f"Unexpected response format: {album_details_response}")
                        continue

                    for album_details in album_details_response["albums"]:
                        # Extract necessary details with safety checks
                        album_id = album_details.get("id")
                        name = album_details.get("name")
                        artist_id = album_details["artists"][0]["id"] if album_details.get("artists") else None
                        image_url = album_details["images"][0]["url"] if album_details.get("images") else None
                        spotify_url = album_details.get("external_urls", {}).get("spotify")

                        if not album_id or not name or not artist_id:
                            print(f"Missing required album data for album {album_id}")
                            continue

                        # Collect unique artist IDs
                        new_artists.add(artist_id)
                        
                        # Store album data
                        tot_albums.append((album_id, name, artist_id, image_url, spotify_url))

                # Update artist details in batches of 50 (Spotify API limit)
                if new_artists:
                    artist_chunks = [list(new_artists)[i:i + 50] for i in range(0, len(new_artists), 50)]
                    for artist_chunk in artist_chunks:
                        await self.update_artist_details(artist_chunk)
                    print("Artist details updated successfully.")

                # Insert the album data into PostgreSQL
                if tot_albums:
                    query = """
                        INSERT INTO albums (album_id, name, artist_id, image_url, spotify_url)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (album_id) DO NOTHING;
                    """
                    await self.db.executemany(query, tot_albums)
                    print("Album details inserted successfully.")

        except Exception as e:
            print(f"Error processing albums: {e}")











async def all_artist_id_and_image_url_into_database(track_data, user_id):
    db = await get_db_connection()
    cursor = await db.cursor()

    try:
        for track in track_data:
            track_id = track.get("id")
            album = track.get("album", {})
            artists = album.get("artists", [])
            images = album.get("images", [])

            if not track_id or not artists:
                continue  # Skip if no valid data

            artist_id = artists[0].get("id") if artists else None
            image_url = images[0]["url"] if images else None

            if artist_id:
                await cursor.execute(
                    "UPDATE listening_history SET artist_id = %s, album_image_url = %s WHERE user_id = %s AND track_id = %s",
                    (artist_id, image_url, user_id, track_id)
                )

        db.commit()
        print("Database updated successfully all artists_id album_url in database.")

    except Exception as e:
        print(f"Database update error all artists_id album_url in database: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()




def process_data(data):
    """Processes the API response data."""
    if "tracks" in data:
        for track in data["tracks"]:
            print(f"Processing track: {track.get('name', 'Unknown')} by {track.get('artists', 'Unknown')}")
            # You can save track info to a database or a list
    else:
        print("Unexpected response format:", data)




async def get_tracks(token, track_ids):
    batch_size = 20  # Spotify allows up to 50 tracks per request
    for i in range(0, len(track_ids), batch_size):
        batch = track_ids[i:i+batch_size]
        
        response = await SpotifyClient.get_track(batch, token)  # Your function for API calls
        
        if response.status_code == 429:  # Too many requests
            retry_after = int(response.headers.get("Retry-After", 5))  # Get wait time from response
            print(f"Rate limit hit. Waiting {retry_after} seconds...")
            time.sleep(retry_after)  # Wait before retrying
            continue  # Retry the same batch

        elif response.status_code == 200:
            await process_data(response.json())  # Process the successful response
        
        else:
            print(f"Error fetching batch {i}-{i+batch_size}: {response.status_code}")



