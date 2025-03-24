from app.database import get_db_connection
import json, asyncpg
from datetime import datetime
import psycopg2  # Assuming you are using PostgreSQL

async def top_artists_to_database(top_artists, user_id, time_range):
    db = await get_db_connection()
    if db is None:
        print("Failed to connect to the database.")
        return

    try:
        async with db.transaction():
            # Step 1: Delete old records for this user and time_range
            await db.execute(
                "DELETE FROM users_top_artists WHERE user_id = $1 AND time_range = $2;",
                user_id, time_range
            )

            # Step 2: Prepare the new data for insertion
            top_artist = [
                (
                    user_id,
                    artist["id"],
                    artist["name"],
                    artist["external_urls"]["spotify"],
                    artist.get("followers", {}).get("total", 0),
                    ", ".join(artist.get("genres", [])) if artist.get("genres") else None,
                    artist["images"][0]["url"] if artist.get("images") else None,
                    index + 1,  # Rank from API
                    artist["uri"],
                    time_range,
                )
                for index, artist in enumerate(top_artists["items"])
            ]

            # Step 3: Insert new data
            if top_artist:
                await db.executemany(
                    """
                    INSERT INTO users_top_artists 
                    (user_id, artist_id, artist_name, spotify_url, followers, genres, image_url, rank, uri, time_range) 
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10);
                    """,
                    top_artist
                )
            else:
                print("No new top artists to add.")

    except Exception as e:
        print(f"Database insertion error in top_artists_to_database: {e}")
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




async def top_tracks_to_database(top_tracks, user_id, time_range):
    db = await get_db_connection()  # ✅ Await the async function

    try:
        top_records = []
        for index, track in enumerate(top_tracks["items"]):

            track_id = track["id"]
            track_name = track["name"]
            artist_id = track["artists"][0]["id"]
            artist_name = track["artists"][0]["name"]
            album_id = track["album"]["id"] 
            album_name = track["album"]["name"]
            album_image_url = track["album"]["images"][0]["url"] if track["album"]["images"] else None
            
            # ✅ Convert release_date to a proper datetime.date object
            release_date_str = track["album"]["release_date"]
            if len(release_date_str) == 10:  # Format: YYYY-MM-DD
                release_date = datetime.strptime(release_date_str, "%Y-%m-%d").date()
            elif len(release_date_str) == 7:  # Format: YYYY-MM (some Spotify data)
                release_date = datetime.strptime(release_date_str, "%Y-%m").date()
            elif len(release_date_str) == 4:  # Format: YYYY
                release_date = datetime.date(int(release_date_str), 1, 1)  # Default to January 1st
            else:
                release_date = None  # Handle unexpected formats safely

            duration_ms = track["duration_ms"]
            is_explicit = track["explicit"]
            spotify_url = track["external_urls"]["spotify"]
            popularity = track["popularity"]
            rank = index + 1

            top_records.append((user_id, track_id, track_name, artist_id, artist_name, album_id, album_name, album_image_url, release_date, duration_ms, is_explicit, spotify_url, popularity, rank))

        if top_records:
            query = """
                INSERT INTO top_tracks 
                (user_id, track_id, track_name, artist_id, artist_name, album_id, album_name, 
                 album_image_url, release_date, duration_ms, is_explicit, spotify_url, popularity, rank) 
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14) 
                ON CONFLICT (user_id, track_id) 
                DO UPDATE SET rank = EXCLUDED.rank
            """

            async with db.transaction():  # ✅ Use transaction context instead of manual rollback
                await db.executemany(query, top_records)

        else:
            print("There are no top tracks for this user")

    except Exception as e:
        print(f"Database insertion error in crud.py top_tracks_to_database: {e}")

    finally:
        await db.close()  # ✅ Close connection




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



