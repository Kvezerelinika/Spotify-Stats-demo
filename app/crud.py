from app.database import get_db_connection
from app.spotify_api import SpotifyClient
import json, time
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import text
from app.db import UsersTopArtists, Artist, UsersTopTracks, Track, Album, TrackArtist


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
        try:
            # Get all existing artist IDs
            result = await self.db.execute(select(Artist.artist_id))
            existing_artist_ids = {row[0] for row in result.all()}

            new_artist_ids = [artist["id"] for artist in top_artists["items"] if artist["id"] not in existing_artist_ids]

            if new_artist_ids:
                await self.update_artist_details(new_artist_ids)

                result = await self.db.execute(select(Artist.artist_id))
                existing_artist_ids = {row[0] for row in result.all()}

            current_time = datetime.now(timezone.utc)
            if current_time.tzinfo is not None:
                current_time = current_time.replace(tzinfo=None)


            # Delete existing user artist rankings for this time_range
            await self.db.execute(
                delete(UsersTopArtists)
                .where(UsersTopArtists.user_id == self.user_id)
                .where(UsersTopArtists.time_range == time_range)
            )

            # Prepare records to insert
            top_artist_records = [
                {
                    "user_id": self.user_id,
                    "artist_id": artist["id"],
                    "rank": index + 1,
                    "time_range": time_range,
                    "last_updated": current_time
                }
                for index, artist in enumerate(top_artists["items"])
                if artist["id"] in existing_artist_ids
            ]

            if top_artist_records:
                stmt = insert(UsersTopArtists).values(top_artist_records)
                await self.db.execute(stmt)
                print("Top artists data inserted successfully.")

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            print(f"[error] save_top_artists: {e}")       



    async def update_artist_details(self, artist_ids: list[str]):
        print("Enriching artist details in the database...")

        if not self.db:
            raise Exception("Database connection not initialized.")

        try:
            for i in range(0, len(artist_ids), 50):
                batch = artist_ids[i:i+50]

                try:
                    client = SpotifyClient(self.token)
                    data = await client.get_all_artists(batch)
                    artists_list = data.get("artists", [])
                except Exception as e:
                    print(f"Failed to fetch artist batch: {e}")
                    continue

                if not artists_list:
                    continue

                artist_updates = []
                for artist in artists_list:
                    genres = artist.get("genres") or None
                    artist_updates.append((
                        artist["id"],
                        artist["name"],
                        genres,
                        artist["images"][0]["url"] if artist.get("images") else None,
                        artist["external_urls"]["spotify"],
                        artist["followers"]["total"],
                        artist["popularity"],
                        artist["uri"],
                    ))

                if artist_updates:
                    query = text("""
                        INSERT INTO artists (artist_id, name, genres, image_url, spotify_url, followers, popularity, uri)
                        VALUES (:id, :name, :genres, :image_url, :spotify_url, :followers, :popularity, :uri)
                        ON CONFLICT (artist_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            genres = EXCLUDED.genres,
                            image_url = EXCLUDED.image_url,
                            spotify_url = EXCLUDED.spotify_url,
                            followers = EXCLUDED.followers,
                            popularity = EXCLUDED.popularity,
                            uri = EXCLUDED.uri
                    """)

                    values = [
                        {
                            "id": a[0], "name": a[1], "genres": a[2], "image_url": a[3],
                            "spotify_url": a[4], "followers": a[5], "popularity": a[6], "uri": a[7]
                        }
                        for a in artist_updates
                    ]

                    for v in values:
                        await self.db.execute(query, v)

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            print(f"Database insertion error in update_artist_details: {e}")



    async def top_tracks_to_database(self, top_tracks: dict, time_range: str):
        print("Inserting top tracks data into the database...")

        try:
            # Step 1: Delete existing top tracks for this user and time range
            delete_existing_data_query = text("""
                DELETE FROM users_top_tracks 
                WHERE user_id = :user_id AND time_range = :time_range;
            """)
            await self.db.execute(delete_existing_data_query, {
                "user_id": self.user_id,
                "time_range": time_range
            })

            # Step 2: Prepare new top tracks data
            top_records = []
            top_track_ids = []

            for index, track in enumerate(top_tracks["items"]):
                track_id = track["id"]
                rank = index + 1

                top_records.append({
                    "user_id": self.user_id,
                    "track_id": track_id,
                    "rank": rank,
                    "time_range": time_range,
                    "last_updated": datetime.now().date()
                })
                top_track_ids.append(track_id)

            # Step 3: Ensure track metadata exists
            if top_track_ids:
                await self.update_tracks_details(top_track_ids)

            # Step 4: Insert top tracks into `users_top_tracks`
            if top_records:
                insert_query = text("""
                    INSERT INTO users_top_tracks 
                    (user_id, track_id, rank, time_range, last_updated) 
                    VALUES (:user_id, :track_id, :rank, :time_range, :last_updated)
                """)
                for record in top_records:
                    await self.db.execute(insert_query, record)

                print("Top tracks data inserted successfully.")
            else:
                print("No top tracks to insert.")

            await self.db.commit()

        except Exception as e:
            print(f"[error] top_tracks_to_database: {e}")  




    async def update_tracks_details(self, track_ids: list[str]):
        print("Enriching tracks database with new track details...")

        if not self.db:
            raise Exception("Database session not initialized.")

        try:
            track_updates = []
            track_artist_relationships = []
            artists_id_to_add = set()
            album_ids_to_add = set()

            batch_size = 50
            track_id_batches = [track_ids[i:i + batch_size] for i in range(0, len(track_ids), batch_size)]

            for batch in track_id_batches:
                try:
                    client = SpotifyClient(self.token)
                    tracks_details = await client.get_track(batch)

                    for track in tracks_details.get("tracks", []):
                        if not track:
                            continue

                        track_id = track["id"]
                        track_name = track.get("name", "Unknown")
                        artist_ids = [artist["id"] for artist in track.get("artists", []) if artist.get("id")]
                        artist_names = [artist.get("name", "Unknown") for artist in track.get("artists", [])]

                        album = track.get("album", {})
                        album_id = album.get("id")
                        album_name = album.get("name", "Unknown")
                        album_image_url = next((img["url"] for img in album.get("images", []) if img["height"] == 640), None)
                        if not album_image_url and album.get("images"):
                            album_image_url = album["images"][0]["url"]

                        release_date = self.parse_release_date(album.get("release_date"))
                        duration_ms = track.get("duration_ms", 0)
                        is_explicit = track.get("explicit", False)
                        spotify_url = track.get("external_urls", {}).get("spotify", "")
                        popularity = track.get("popularity", 0)
                        track_number = track.get("track_number", 0)

                        artists_id_to_add.update(artist_ids)
                        if album_id:
                            album_ids_to_add.add(album_id)

                        track_updates.append({
                            "track_id": track_id,
                            "name": track_name,
                            "album_id": album_id,
                            "artist_id": artist_ids[0] if artist_ids else None,
                            "spotify_url": spotify_url,
                            "duration_ms": duration_ms,
                            "popularity": popularity,
                            "explicit": is_explicit,
                            "track_number": track_number,
                            "album_release_date": release_date,
                            "album_image_url": album_image_url,
                            "album_name": album_name,
                            "artist_name": artist_names[0] if artist_names else None
                        })

                        for artist_id in artist_ids:
                            track_artist_relationships.append({
                                "track_id": track_id,
                                "artist_id": artist_id
                            })

                except Exception as batch_error:
                    print(f"Error fetching details for batch {batch}: {batch_error}")
                    continue

            if artists_id_to_add:
                await self.update_artist_details(list(artists_id_to_add))

            if album_ids_to_add:
                await self.all_albums_to_database(list(album_ids_to_add))

            if track_updates:
                print("Inserting/updating track details into the database...")
                async with self.db.begin():
                    for data in track_updates:
                        stmt = insert(Track).values(**data)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=['track_id'],
                            set_={
                                "name": data["name"],
                                "album_id": data["album_id"],
                                "artist_id": data["artist_id"],
                                "artist_name": data["artist_name"],
                                "spotify_url": data["spotify_url"],
                                "duration_ms": data["duration_ms"],
                                "popularity": data["popularity"],
                                "explicit": data["explicit"],
                                "track_number": data["track_number"],
                                "album_release_date": data["album_release_date"],
                                "album_image_url": data["album_image_url"],
                                "album_name": data["album_name"]
                            }
                        )
                        await self.db.execute(stmt)

                    print("Track details inserted/updated successfully.")

            if track_artist_relationships:
                print("Inserting track-artist relationships into the database...")

                async with self.db.begin():
                    for rel in track_artist_relationships:
                        stmt = insert(TrackArtist).values(**rel)
                        stmt = stmt.on_conflict_do_nothing()
                        await self.db.execute(stmt)

                print("Track-artist relationships inserted successfully.")
            else:
                print("No track-artist relationships to insert.")

            await self.retry_update_tracks_if_needed()

        except Exception as e:
            print(f"[error] update_tracks_details: {e}")        



    async def retry_update_tracks_if_needed(self):
        query = text("""
            SELECT track_id FROM tracks
            WHERE artist_name IS NULL OR artist_name = 'Unknown'
        """)
        result = await self.db.execute(query)
        rows = result.mappings().all()

        if rows:
            missing_track_ids = [row['track_id'] for row in rows]
            print(f"Retrying update for tracks with missing artist names: {missing_track_ids}")
            await self.update_tracks_details(missing_track_ids)


    def parse_release_date(self, release_date_str):
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
        if not recent_tracks:
            print("No recent tracks to process.")
            return

        track_id_to_add = set()

        if isinstance(recent_tracks, str):
            try:
                recent_tracks = json.loads(recent_tracks)
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON: {e}")
                return

        if not isinstance(recent_tracks, list) or not all(isinstance(track, dict) for track in recent_tracks):
            print(f"Invalid format for recent_tracks: {type(recent_tracks)}")
            return

        track_ids = {track["track"]["id"] for track in recent_tracks if "track" in track and "id" in track["track"]}

        # ✅ STEP 1: Ensure track details are in DB (run outside transaction!)
        if track_ids:
            print("FROM RECENT TO TRACKS UPDATE IDS: ", track_ids)
            await self.update_tracks_details(list(track_ids))
            await self.db.commit()

        try:
            # ✅ STEP 2: Insert into listening_history (new transaction)
            insert_query = text("""
                INSERT INTO listening_history (user_id, track_id, played_at)
                VALUES (:user_id, :track_id, :played_at)
                ON CONFLICT (user_id, track_id, played_at) DO NOTHING;
            """)

            async with self.db.begin():
                for track in recent_tracks:
                    track_data = track.get("track")
                    if track_data and "id" in track_data and "played_at" in track:
                        track_id = track_data["id"]
                        track_id_to_add.add(track_id)

                        played_at_str = track["played_at"]
                        try:
                            played_at = datetime.fromisoformat(played_at_str.replace('Z', '+00:00'))
                            played_at = played_at.replace(tzinfo=None)
                        except ValueError as e:
                            print(f"Error parsing datetime: {e}")
                            continue

                        await self.db.execute(insert_query, {
                            "user_id": self.user_id,
                            "track_id": track_id,
                            "played_at": played_at
                        })

        except Exception as e:
            print(f"Database insertion error in recents_to_database: {e}")




    async def all_albums_to_database(self, album_ids):
        print("Fetching album details from Spotify...")
        tot_albums = []
        new_artists = set()

        # Fetch all albums and artist IDs first
        album_chunks = [album_ids[i:i + 20] for i in range(0, len(album_ids), 20)]

        for chunk in album_chunks:
            client = SpotifyClient(self.token)
            album_details_response = await client.get_all_albums(chunk)

            if "albums" not in album_details_response:
                print(f"Unexpected response format: {album_details_response}")
                continue

            for album_details in album_details_response["albums"]:
                album_id = album_details.get("id")
                name = album_details.get("name")
                artist_id = album_details["artists"][0]["id"] if album_details.get("artists") else None
                image_url = album_details["images"][0]["url"] if album_details.get("images") else None
                spotify_url = album_details.get("external_urls", {}).get("spotify")

                if not album_id or not name or not artist_id:
                    print(f"Missing required album data for album {album_id}")
                    continue

                new_artists.add(artist_id)
                tot_albums.append((album_id, name, artist_id, image_url, spotify_url))

        # Fetch artist details first (API call)
        if new_artists:
            artist_chunks = [list(new_artists)[i:i + 50] for i in range(0, len(new_artists), 50)]
            for artist_chunk in artist_chunks:
                await self.update_artist_details(artist_chunk)

        print("Inserting into database...")

        # Now begin DB transaction
        try:
            async with self.db.begin():
                if tot_albums:
                    query = text("""
                        INSERT INTO albums (album_id, name, artist_id, image_url, spotify_url)
                        VALUES (:album_id, :name, :artist_id, :image_url, :spotify_url)
                        ON CONFLICT (album_id) DO NOTHING;
                    """)

                    for album in tot_albums:
                        await self.db.execute(query, {
                            "album_id": album[0],
                            "name": album[1],
                            "artist_id": album[2],
                            "image_url": album[3],
                            "spotify_url": album[4]
                        })

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



