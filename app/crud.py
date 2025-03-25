from app.database import get_db_connection
from app.spotify_api import get_all_artist, get_track
import json, asyncpg
from datetime import datetime
import psycopg2  # Assuming you are using PostgreSQL

async def top_artists_to_database(top_artists, user_id, time_range, current_time):
    """Saves top artists rankings into users_top_artists, and only sends unique artist_ids to update_artist_details."""
    db = await get_db_connection()
    if db is None:
        print("Failed to connect to the database.")
        return

    try:
        # Step 1: Delete the existing top artists data for the given user_id and time_range
        delete_existing_data_query = """
            DELETE FROM users_top_artists WHERE user_id = $1 AND time_range = $2;
        """
        await db.execute(delete_existing_data_query, user_id, time_range)

        # Step 2: Prepare the new top artists data and insert into users_top_artists
        top_artists_data = [
            (
                user_id,
                artist["id"],  # Artist ID
                index + 1,  # Rank
                time_range,  # Time range for the data
                current_time,  # Last updated timestamp
            )
            for index, artist in enumerate(top_artists["items"])
        ]
        
        # Step 3: Insert the new top artists data into the users_top_artists table
        if top_artists_data:
            await db.executemany(
                """
                INSERT INTO users_top_artists (user_id, artist_id, rank, time_range, last_updated)
                VALUES ($1, $2, $3, $4, $5);
                """,
                top_artists_data
            )

        # Step 4: Collect unique artist_ids from top_artists that are not already in users_top_artists
        artist_ids_to_update = [
            artist["id"]
            for artist in top_artists["items"]
        ]

        # Step 5: Check for artist IDs that are not already in the artists table
        # Get the artist_ids already in the artists table
        existing_artists_query = """
            SELECT artist_id FROM artists
        """
        existing_artists_result = await db.fetch(existing_artists_query)
        existing_artists_ids = {row["artist_id"] for row in existing_artists_result}

        # Filter out artist_ids that are already in the artists table
        artist_ids_to_update = [
            artist_id for artist_id in artist_ids_to_update
            if artist_id not in existing_artists_ids  # Only include artists missing from the artists table
        ]

        # Step 6: If there are new artist_ids to update, send them to update_artist_details
        if artist_ids_to_update:
            await update_artist_details(artist_ids_to_update)
        else:
            print("No new artist data to enrich.")

    except Exception as e:
        print(f"Database insertion error in top_artists_to_database: {e}")
    finally:
        await db.close()





async def update_artist_details(artist_ids):
    """Updates the artists table with the given artist details in batches of 50."""
    db = await get_db_connection()

    try:
        artist_updates = []

        # Process artist_ids in batches of 50
        for i in range(0, len(artist_ids), 50):
            batch_artist_ids = artist_ids[i:i+50]

            for artist_id in batch_artist_ids:
                # Fetch the artist details from Spotify API
                artist_details = await get_all_artist(artist_id)

                # Extract necessary details
                artist_name = artist_details["name"]
                genres = ", ".join(artist_details.get("genres", [])) if artist_details.get("genres") else None
                image_url = artist_details["images"][0]["url"] if artist_details.get("images") else None
                spotify_url = artist_details["external_urls"]["spotify"]
                followers = artist_details["followers"]["total"]
                popularity = artist_details["popularity"]
                uri = artist_details["uri"]

                # Prepare the artist data for the update
                artist_updates.append((
                    artist_id, artist_name, genres, image_url, spotify_url, followers, popularity, uri
                ))

            # After processing 50 artist IDs, update the database
            if artist_updates:
                insert_or_update_query = """
                    INSERT INTO artists (artist_id, name, genres, image_url, spotify_url, followers, popularity, uri)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
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




async def top_tracks_to_database(top_tracks, user_id, time_range):
    db = await get_db_connection()  # ✅ Await the async function

    try:
        # Step 1: Delete the existing top tracks data for the given user_id and time_range
        delete_existing_data_query = """
            DELETE FROM users_top_tracks WHERE user_id = $1 AND time_range = $2;
        """
        await db.execute(delete_existing_data_query, user_id, time_range)

        # Step 2: Prepare the new top tracks data
        top_records = []
        top_track_ids = set()  # To keep track of all track IDs in the current top tracks

        for index, track in enumerate(top_tracks["items"]):
            track_id = track["id"]
            rank = index + 1  # Rank is based on the index (1-based)

            # Save only the essential information in the top_tracks table
            top_records.append((user_id, track_id, rank, time_range, datetime.now()))
            top_track_ids.add(track_id)

        # Step 3: Insert new top tracks data into the users_top_tracks table
        if top_records:
            query = """
                INSERT INTO users_top_tracks 
                (user_id, track_id, rank, time_range, last_updated) 
                VALUES ($1, $2, $3, $4, $5)
            """

            async with db.transaction():  # ✅ Use transaction context instead of manual rollback
                await db.executemany(query, top_records)

            # Step 4: Get all track_ids for the specific user from the users_top_tracks table
            check_existing_query = """
                SELECT DISTINCT track_id FROM users_top_tracks WHERE user_id = $1
            """
            existing_tracks = await db.fetch(check_existing_query, user_id)

            # Step 5: Extract existing track_ids into a set
            existing_track_ids = {track["track_id"] for track in existing_tracks}

            # Step 6: Find track_ids that are in the top tracks but not yet in the tracks table
            missing_track_ids = list(top_track_ids - existing_track_ids)

            # Step 7: Get all track_ids from the tracks table to compare
            existing_tracks_query = """
                SELECT track_id FROM tracks
            """
            existing_tracks_in_db = await db.fetch(existing_tracks_query)
            existing_tracks_in_db_ids = {track["track_id"] for track in existing_tracks_in_db}

            # Step 8: Filter out track_ids that already have data in the tracks table
            missing_track_ids = [
                track_id for track_id in missing_track_ids
                if track_id not in existing_tracks_in_db_ids
            ]

            # Step 9: Call the update_tracks_details function for the missing track IDs
            if missing_track_ids:
                await update_tracks_details(missing_track_ids)

        else:
            print("There are no top tracks for this user")

    except Exception as e:
        print(f"Database insertion error in crud.py top_tracks_to_database: {e}")

    finally:
        await db.close()  # ✅ Close connection



async def update_tracks_details(track_ids):
    db = await get_db_connection()

    try:
        track_updates = []

        # Split the track_ids into batches of 50
        batch_size = 50
        track_id_batches = [track_ids[i:i + batch_size] for i in range(0, len(track_ids), batch_size)]

        for batch in track_id_batches:
            try:
                # Fetch the details for the current batch of tracks
                tracks_details = await get_track(batch)  # Assuming get_track can handle a batch

                # Iterate over the returned details of the batch
                for track_details in tracks_details:
                    if not track_details:
                        continue  # Skip if track details are missing

                    track_id = track_details["id"]
                    track_name = track_details["name"]
                    artist_id = track_details["artists"][0]["id"]
                    artist_name = track_details["artists"][0]["name"]
                    album_id = track_details["album"]["id"]
                    album_name = track_details["album"]["name"]
                    album_image_url = track_details["album"]["images"][0]["url"] if track_details["album"]["images"] else None
                    release_date = track_details["album"]["release_date"]
                    duration_ms = track_details["duration_ms"]
                    is_explicit = track_details["explicit"]
                    spotify_url = track_details["external_urls"]["spotify"]
                    popularity = track_details["popularity"]
                    track_number = track_details["track_number"]

                    # Prepare the update data for the track
                    track_updates.append((
                        track_id, track_name, album_id, artist_id, spotify_url, duration_ms, popularity, 
                        is_explicit, track_number, release_date, album_image_url, album_name, artist_name
                    ))

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
            print("No tracks to enrich.")

    except Exception as e:
        print(f"Error enriching tracks database: {e}")

    finally:
        await db.close()









async def recents_to_database(recent_tracks, user_id):   
    db = await get_db_connection()

    try:
        recent_records = []
        for item in recent_tracks.get("items", []):
            track = item.get("track", {})

            # Get track details
            track_id = track.get("id")
            track_name = track.get("name")
            artist_id = track.get("artists", [{}])[0].get("id")
            artist_name = track.get("artists", [{}])[0].get("name")
            album_name = track.get("album", {}).get("name")
            album_images = track.get("album", {}).get("images", [])
            album_image_url = album_images[0]["url"] if album_images else None
            duration_ms = track.get("duration_ms")  # Get duration directly from track

            # Convert played_at string to datetime safely
            try:
                played_at = datetime.fromisoformat(item["played_at"].replace("Z", ""))
            except ValueError:
                print(f"Skipping invalid timestamp: {item['played_at']}")
                continue

            # Add record to list
            recent_records.append((
                user_id, track_id, track_name, artist_id, artist_name, 
                album_name, album_image_url, played_at, duration_ms
            ))

        if recent_records:
            # Execute the insert query directly
            await db.executemany(
                """
                INSERT INTO listening_history 
                (user_id, track_id, track_name, artist_id, artist_name, 
                album_name, album_image_url, played_at, duration_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (user_id, played_at)
                DO UPDATE SET album_image_url = EXCLUDED.album_image_url
                WHERE listening_history.album_image_url != EXCLUDED.album_image_url
                """,
                recent_records
            )
            print(f"Successfully inserted {len(recent_records)} records")
        else:
            print("No new tracks played.")

    except psycopg2.Error as e:
        print(f"Database error in recents_to_database: {e}")
        await db.rollback()  # Ensure rollback in case of an error
    
    finally:
        await db.close()  # Ensure connection is closed after the operation





async def all_albums_to_database(all_albums):
    db = await get_db_connection()
    cursor = await db.cursor()

    try:
        tot_albums = []
        for album in all_albums["items"]:

            id = album["id"]
            name = album["name"]
            album_type = album["album_type"]
            total_tracks = album["total_tracks"]
            release_date = album["release_date"]
            release_date_precision = album["release_date_precision"]
            restrictions_reason = album.get("restrictions", {}).get("reason")
            spotify_url = album["external_urls"]["spotify"]
            image_url = album["images"][0]["url"] if album["images"] else None
            uri = album["uri"]
            popularity = album.get("popularity", 0)
            label = album["label"]
            genres = ", ".join(album.get("genres")) if album.get("genres") else None
            external_isrc = album["external_ids"].get("isrc")
            external_ean = album["external_ids"].get("ean")
            external_upc = album["external_ids"].get("upc")

            tot_albums.append((id, name, album_type, total_tracks, release_date, release_date_precision, restrictions_reason, spotify_url, image_url, uri, popularity, label, genres, external_isrc, external_ean, external_upc))

        if tot_albums:
            await cursor.executemany("INSERT INTO albums (id, name, album_type, total_tracks, release_date, release_date_precision, restrictions_reason, spotify_url, image_url, uri, popularity, label, genres, external_isrc,external_ean, external_upc) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)  ON CONFLICT (uri) DO UPDATE SET popularity = EXCLUDED.popularity, genres = EXCLUDED.genres, image_url = EXCLUDED.image_url", tot_albums)
        else:
            print("No new albums to add.")
        
        db.commit()

    except Exception as e:
        print(f"Database insertion error: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()

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



