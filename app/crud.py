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
            top_records.append((user_id, track_id, rank, time_range, datetime.now()))
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

        # Split the track_ids into batches of 50
        batch_size = 50
        track_id_batches = [track_ids[i:i + batch_size] for i in range(0, len(track_ids), batch_size)]

        for batch in track_id_batches:
            print("BATCH: ", batch)
            try:
                # Fetch the details for the current batch of tracks
                tracks_details = await get_track(token, batch)  # Assuming get_track can handle a batch
                #print("TRACKS DETAILS: ", tracks_details)

                album_ids_to_add = set()  # Set to store new album_ids to add

                # Iterate over the returned details of the batch
                for track_details in tracks_details:
                    print("TRACK DETAILS: ", track_details)
                    if not track_details:
                        continue  # Skip if track details are missing

                    track_id = track_details["id"]
                    track_name = track_details["name"]
                    artist_id = track_details["artists"][0]["id"]
                    artist_name = track_details["artists"][0]["name"]
                    album_id = track_details["album"]["id"]
                    album_name = track_details["album"]["name"]
                    album_image_url = next((img["url"] for img in track_details["album"]["images"] if img["height"] == 640), None)
                    release_date = track_details["album"]["release_date"]
                    duration_ms = track_details["duration_ms"]
                    is_explicit = track_details["explicit"]
                    spotify_url = track_details["external_urls"]["spotify"]
                    popularity = track_details["popularity"]
                    track_number = track_details["track_number"]

                    # Add the album_id to the set of albums to add
                    album_ids_to_add.add(album_id)

                    # Prepare the update data for the track
                    track_updates.append((track_id, track_name, album_id, artist_id, spotify_url, duration_ms, popularity, 
                                         is_explicit, track_number, release_date, album_image_url, album_name, artist_name))

                # After processing the batch, send new albums to be added to the database
                if album_ids_to_add:
                    # Call the all_albums_to_database function with the new album_ids
                    await all_albums_to_database(list(album_ids_to_add))

            except Exception as batch_error:
                print(f"Error fetching details for batch {batch}: {batch_error}")
                continue

        # Check if there are tracks to update
        if track_updates:
            insert_or_update_query = """
                INSERT INTO tracks (
                    track_id, name, album_id, artist_id, spotify_url, duration_ms, popularity, 
                    explicit, track_number, album_release_date, album_image_url, album_name, artist_name
                ) 
                VALUES 
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (track_id) 
                DO UPDATE SET
                    name = EXCLUDED.name,
                    album_id = EXCLUDED.album_id,
                    artist_id = EXCLUDED.artist_id,
                    spotify_url = EXCLUDED.spotify_url,
                    duration_ms = EXCLUDED.duration_ms,
                    popularity = EXCLUDED.popularity,
                    explicit = EXCLUDED.explicit,
                    track_number = EXCLUDED.track_number,
                    album_release_date = EXCLUDED.album_release_date,
                    album_image_url = EXCLUDED.album_image_url,
                    album_name = EXCLUDED.album_name,
                    artist_name = EXCLUDED.artist_name
            """

            # Execute the insert/update queries for all tracks
            async with db.transaction():
                await db.executemany(insert_or_update_query, track_updates)

        else:
            print("No tracks to enrich for update_tracks_details.")

    except Exception as e:
        print(f"Error enriching tracks database in crud.py for update_tracks_details: {e}")

    finally:
        await db.close()





import json

async def recents_to_database(user_id, recent_tracks):
    """Stores user's recent listening history in the database."""

    if not recent_tracks:
        print("No recent tracks to process.")
        return

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

    track_ids = {track["id"] for track in recent_tracks if "id" in track}  # Get track IDs safely

    async with get_db_connection() as db:  
        async with db.cursor() as cursor:  
            insert_query = """
            INSERT INTO listening_history (user_id, track_id, played_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, track_id, played_at) DO NOTHING;
            """

            for track in recent_tracks:
                if "id" in track and "played_at" in track:
                    await cursor.execute(insert_query, (user_id, track["id"], track["played_at"]))

            await db.commit()

    if track_ids:
        await update_tracks_details(track_ids)  # Ensure this function is async




async def all_albums_to_database(album_ids):
    db = await get_db_connection()
    cursor = await db.cursor()

    try:
        tot_albums = []

        # Iterate over the album_ids and fetch details for each album
        for album_id in album_ids:
            album_details = await get_all_albums(album_id)

            # Extract necessary details
            album_id = album_details["id"]
            name = album_details["name"]
            artist_id = album_details["artists"][0]["id"]  # Assuming the first artist is the primary artist
            image_url = album_details["images"][0]["url"] if album_details["images"] else None
            spotify_url = album_details["external_urls"]["spotify"]
            release_date = album_details["release_date"]
            popularity = album_details.get("popularity", 0)
            label = album_details.get("label")  # It may not always exist, so handle it gracefully

            # Append the tuple to insert into the database
            tot_albums.append((album_id, name, artist_id, image_url, spotify_url, release_date, popularity, label))

        if tot_albums:
            # Insert or update albums in the database
            await cursor.executemany("""
                INSERT INTO albums (album_id, name, artist_id, image_url, spotify_url, release_date, popularity, label) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) 
                ON CONFLICT (album_id) 
                DO UPDATE SET 
                    popularity = EXCLUDED.popularity, 
                    label = EXCLUDED.label, 
                    image_url = EXCLUDED.image_url
            """, tot_albums)
        else:
            print("No new albums to add.")
        
        await db.commit()

    except Exception as e:
        print(f"Database insertion error: {e}")
        await db.rollback()
    
    finally:
        await cursor.close()
        await db.close()



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



