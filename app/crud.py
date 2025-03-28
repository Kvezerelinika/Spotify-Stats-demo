from app.database import get_db_connection
from app.spotify_api import get_all_artists, get_track, get_all_albums
import json, asyncpg
from datetime import datetime
import psycopg2  # Assuming you are using PostgreSQL
from datetime import datetime, timedelta

async def top_artists_to_database(top_artists, user_id, time_range, current_time, token):
    """Saves top artists rankings into users_top_artists and ensures artist details are inserted first."""
    db = await get_db_connection()
    if db is None:
        print("Failed to connect to the database.")
        return

    try:
        # Step 1: Fetch existing artists to check if they are already in the database
        existing_artists_query = """
            SELECT artist_id FROM artists;
        """
        existing_artists_result = await db.fetch(existing_artists_query)
        existing_artists = {row["artist_id"] for row in existing_artists_result}

        # Step 2: Identify new artists that need to be inserted
        new_artists = [artist["id"] for artist in top_artists["items"] if artist["id"] not in existing_artists]

        # Step 3: Insert new artists before adding them to users_top_artists
        if new_artists:
            await update_artist_details(token, new_artists)  # Ensure new artists are added

            # Re-fetch existing artists to confirm insertion
            existing_artists_result = await db.fetch(existing_artists_query)
            existing_artists = {row["artist_id"] for row in existing_artists_result}

        # Step 4: Delete existing top artists for the user and time range
        delete_existing_data_query = """
            DELETE FROM users_top_artists WHERE user_id = $1 AND time_range = $2;
        """
        await db.execute(delete_existing_data_query, user_id, time_range)

        # Step 5: Prepare and insert new top artists data
        top_artists_data = [
            (
                user_id,
                artist["id"],  # Artist ID
                index + 1,  # Rank
                time_range,  # Time range
                current_time,  # Last updated timestamp
            )
            for index, artist in enumerate(top_artists["items"])
            if artist["id"] in existing_artists  # Ensure only existing artists are inserted
        ]
        
        if top_artists_data:
            await db.executemany(
                """
                INSERT INTO users_top_artists (user_id, artist_id, rank, time_range, last_updated)
                VALUES ($1, $2, $3, $4, $5);
                """,
                top_artists_data
            )
            print("Top artists data inserted successfully.")
    
    except Exception as e:
        print(f"Database insertion error in top_artists_to_database: {e}")
    finally:
        await db.close()




async def update_artist_details(token, artist_ids):
    print("Enriching artist details in the database...")
    """Updates the artists table with the given artist details in batches of 50."""
    db = await get_db_connection()

    try:
        artist_updates = []

        # Process artist_ids in batches of 50
        for i in range(0, len(artist_ids), 50):
            batch_artist_ids = artist_ids[i:i+50]

            for artist_id in batch_artist_ids:
                # Fetch the artist details from Spotify API
                try:
                    artist_details = await get_all_artists(token, artist_id)

                    # Extract necessary details
                    artist_name = artist_details["name"]
                    genres = artist_details.get("genres", [])  # Ensure genres is always a list
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
                    print(f"Failed to get artist details for {artist_id}: {e}")
                    continue  # Skip to the next artist

            # After processing 50 artist IDs, update the database
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
                print("Finished inserting artist details into the database...")


                # Execute the insert/update queries for this batch of artists
                async with db.transaction():
                    await db.executemany(insert_or_update_query, artist_updates)

                # Reset artist_updates for the next batch
                artist_updates = []

        if not artist_ids:
            print("No artist data to enrich.")

    except Exception as e:
        print(f"Database insertion error in update_artist_details: {e}")

    finally:
        print("Closing the database connection for update_artist_details...")
        await db.close()




async def top_tracks_to_database(top_tracks, user_id, time_range, token):
    print("Inserting top tracks data into the database...")
    db = await get_db_connection()  # ✅ Await the async function

    try:
        # Step 1: Delete existing top tracks for this user and time range
        async with db.transaction():  
            delete_existing_data_query = """
                DELETE FROM users_top_tracks WHERE user_id = $1 AND time_range = $2;
            """
            await db.execute(delete_existing_data_query, user_id, time_range)

        # Step 2: Prepare new top tracks data
        top_records = []
        top_track_ids = set()

        for index, track in enumerate(top_tracks["items"]):
            track_id = track["id"]
            rank = index + 1  # Rank is based on the index (1-based)

            # Save only essential information
            top_records.append((user_id, track_id, rank, time_range, datetime.now().date()))
            top_track_ids.add(track_id)

        # Step 3: Ensure tracks exist in the tracks table
        if top_track_ids:
            await update_tracks_details(list(top_track_ids), token)  # Convert set to list

        # Step 4: Insert new top tracks data
        if top_records:
            async with db.transaction():  # ✅ Ensure atomic insertion
                query = """
                    INSERT INTO users_top_tracks 
                    (user_id, track_id, rank, time_range, last_updated) 
                    VALUES ($1, $2, $3, $4, $5);
                """
                await db.executemany(query, top_records)

        else:
            print("No top tracks to insert.")

    except Exception as e:
        print(f"Database insertion error in crud.py top_tracks_to_database: {e}")

    finally:
        await db.close()  # ✅ Close connection properly





async def update_tracks_details(track_ids, token):
    print("Enriching tracks database with new track details...")
    db = await get_db_connection()

    try:
        track_updates = []
        track_artist_relationships = []  # List to store track-artist relationships

        # Split the track_ids into batches of 50
        batch_size = 50
        track_id_batches = [track_ids[i:i + batch_size] for i in range(0, len(track_ids), batch_size)]

        for batch in track_id_batches:
            try:
                # Fetch the details for the current batch of tracks
                tracks_details = await get_track(token, batch)  # Assuming get_track can handle a batch

                artists_id_to_add = set()
                album_ids_to_add = set()  # Set to store new album_ids to add

                # Iterate over the returned details of the batch
                for track_details in tracks_details.get("tracks", []):
                    if not track_details:
                        continue  # Skip if track details are missing

                    track_id = track_details.get("id")
                    track_name = track_details.get("name", "Unknown")
                    
                    # Collect all artist IDs for this track
                    artist_ids = [artist.get("id", "Unknown") for artist in track_details.get("artists", [])]

                    # Collect all artist names for this track
                    artist_names = [artist.get("name", "Unknown") for artist in track_details.get("artists", [])]

                    # Ensure 'album' exists before accessing its properties
                    album_details = track_details.get("album", {})
                    album_id = album_details.get("id", "Unknown")
                    album_name = album_details.get("name", "Unknown")
                    
                    # Select the highest resolution album image available
                    album_image_url = next((img["url"] for img in album_details.get("images", []) if img["height"] == 640), None)
                    if not album_image_url and album_details.get("images"):  # Fallback to the first available image
                        album_image_url = album_details["images"][0]["url"]

                    # Convert release_date string to a datetime.date object
                    release_date_str = album_details.get("release_date", None)
                    release_date = datetime.strptime(release_date_str, "%Y-%m-%d").date() if release_date_str else None

                    duration_ms = track_details.get("duration_ms", 0)
                    is_explicit = track_details.get("explicit", False)
                    spotify_url = track_details["external_urls"].get("spotify", "") if track_details.get("external_urls") else ""
                    popularity = track_details.get("popularity", 0)
                    track_number = track_details.get("track_number", 0)

                    # Add all artist_ids to the set of artists to add
                    artists_id_to_add.update(artist_ids)

                    # Add the album_id to the set of albums to add
                    album_ids_to_add.add(album_id)

                    # Prepare the update data for the track
                    track_updates.append((track_id, track_name, album_id, spotify_url, duration_ms, popularity, 
                                        is_explicit, track_number, release_date, album_image_url, album_name))

                    # Prepare the track-artist relationships
                    for artist_id in artist_ids:
                        track_artist_relationships.append((track_id, artist_id))

                # Commit artists before albums and tracks
                if artists_id_to_add:
                    await update_artist_details(token, list(artists_id_to_add))

                # Commit albums after artists
                if album_ids_to_add:
                    await all_albums_to_database(token, list(album_ids_to_add))

            except Exception as batch_error:
                print(f"Error fetching details for batch {batch}: {batch_error}")
                continue

        # After the batch process, insert/update the tracks
        if track_updates:
            print("Inserting/updating track details into the database...")
            insert_or_update_query = """
                INSERT INTO tracks (
                    track_id, name, album_id, spotify_url, duration_ms, popularity, 
                    explicit, track_number, album_release_date, album_image_url, album_name
                ) 
                VALUES 
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (track_id) 
                DO UPDATE SET
                    name = EXCLUDED.name,
                    album_id = EXCLUDED.album_id,
                    spotify_url = EXCLUDED.spotify_url,
                    duration_ms = EXCLUDED.duration_ms,
                    popularity = EXCLUDED.popularity,
                    explicit = EXCLUDED.explicit,
                    track_number = EXCLUDED.track_number,
                    album_release_date = EXCLUDED.album_release_date,
                    album_image_url = EXCLUDED.album_image_url,
                    album_name = EXCLUDED.album_name
            """

            # Execute the insert/update queries for all tracks
            async with db.transaction():
                print("Executing batch insert/update for tracks...")
                await db.executemany(insert_or_update_query, track_updates)
                print("Track details inserted/updated successfully.")

        # Insert track-artist relationships into the track_artists table
        if track_artist_relationships:
            print("Inserting track-artist relationships into the database...")
            insert_track_artist_query = """
                INSERT INTO track_artists (track_id, artist_id)
                VALUES ($1, $2)
                ON CONFLICT (track_id, artist_id) DO NOTHING
            """

            # Execute the insert queries for all track-artist relationships
            async with db.transaction():
                await db.executemany(insert_track_artist_query, track_artist_relationships)
                print("Track-artist relationships inserted successfully.")

        else:
            print("No tracks to enrich for update_tracks_details.")

    except Exception as e:
        print(f"Error enriching tracks database in crud.py for update_tracks_details: {e}")

    finally:
        await db.close()






import json

async def recents_to_database(user_id, recent_tracks, token):
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
    db_connection = await get_db_connection()  # Await the connection coroutine

    try:
        # Start a transaction explicitly
        async with db_connection.transaction():
            # First, update track details for the tracks being added
            if track_ids:
                await update_tracks_details(list(track_ids), token)

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
                    await db_connection.execute(insert_query, user_id, track_id, played_at)

    finally:
        # Ensure the connection is closed after the operation
        await db_connection.close()

    # If track_ids exist, update track details again (if needed)
    if track_ids:
        await update_tracks_details(list(track_ids), token)  # Ensure this function is async












import asyncio

async def all_albums_to_database(token, album_ids):
    print("Inserting album details into the database...")
    db = await get_db_connection()

    try:
        async with db.transaction():
            tot_albums = []

            # Helper function to batch album_ids into chunks of 20
            def chunkify(lst, size):
                return [lst[i:i + size] for i in range(0, len(lst), size)]

            # Split album_ids into chunks of 20
            album_chunks = chunkify(album_ids, 20)

            # Process each chunk asynchronously
            for chunk in album_chunks:
                # Get the album details for all albums in this chunk
                album_details_list = await asyncio.gather(*[get_all_albums(token, album_id) for album_id in chunk])

                for album_details in album_details_list:
                    # Ensure the response is a dictionary
                    if not isinstance(album_details, dict):
                        print(f"Error: Expected dictionary for album, got {type(album_details)}")
                        continue

                    # Extract necessary details with safety checks
                    album_id = album_details.get("id")
                    name = album_details.get("name")
                    artist_id = album_details["artists"][0]["id"] if album_details.get("artists") else None
                    image_url = album_details["images"][0]["url"] if album_details.get("images") else None
                    spotify_url = album_details.get("external_urls", {}).get("spotify")

                    if not album_id or not name or not artist_id:
                        print(f"Missing required album data for album {album_id}")
                        continue

                    # Process the album data, e.g., saving to the database
                    tot_albums.append({
                        "album_id": album_id,
                        "name": name,
                        "artist_id": artist_id,
                        "image_url": image_url,
                        "spotify_url": spotify_url,
                    })

            # Insert the album data into PostgreSQL
            if tot_albums:
                query = """
                    INSERT INTO albums (album_id, name, artist_id, image_url, spotify_url)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (album_id) DO NOTHING;
                """
                # Using asyncpg to execute the query
                await db.executemany(query, [
                    (album['album_id'], album['name'], album['artist_id'], album['image_url'], album['spotify_url'])
                    for album in tot_albums
                ])
                print("Album details inserted successfully.")

    except Exception as e:
        print(f"Error processing albums: {e}")







async def all_artists_to_database(top_artists):
    db = await get_db_connection()
    cursor = await db.cursor()


    try:
        artist_records = []
        for artist in top_artists["items"]:
            artist_id = artist["id"]
            name = artist["name"]
            popularity = artist.get("popularity", 0)
            followers = artist.get("followers", {}).get("total", 0)
            genres = ", ".join(artist.get("genres")) if artist.get("genres") else None
            image_url = artist["images"][0]["url"] if artist["images"] else None
            api_data = json.dumps(artist)

            artist_records.append((artist_id, name, popularity, followers, genres, image_url, api_data))

        if artist_records:
            await cursor.executemany("INSERT INTO all_artists (artist_id, name, popularity, followers, genres, image_url, api_data) VALUES (%s, %s, %s, %s, %s, %s, %s)  ON CONFLICT (artist_id) DO UPDATE SET followers = EXCLUDED.followers, popularity = EXCLUDED.popularity, genres = EXCLUDED.genres, image_url = EXCLUDED.image_url", artist_records)
        else: 
            print("No artist here")
        db.commit()

    except Exception as e:
        print(f"Database insertion error: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()

















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


import json
import time
from app.spotify_api import get_track
from fastapi import Request

async def get_tracks(token, track_ids):
    batch_size = 20  # Spotify allows up to 50 tracks per request
    for i in range(0, len(track_ids), batch_size):
        batch = track_ids[i:i+batch_size]
        
        response = await get_track(batch, token)  # Your function for API calls
        
        if response.status_code == 429:  # Too many requests
            retry_after = int(response.headers.get("Retry-After", 5))  # Get wait time from response
            print(f"Rate limit hit. Waiting {retry_after} seconds...")
            time.sleep(retry_after)  # Wait before retrying
            continue  # Retry the same batch

        elif response.status_code == 200:
            await process_data(response.json())  # Process the successful response
        
        else:
            print(f"Error fetching batch {i}-{i+batch_size}: {response.status_code}")



