from app.database import get_db_connection
import json
from datetime import datetime
import psycopg2  # Assuming you are using PostgreSQL
from app.spotify_api import get_tracks

def top_artists_to_database(top_artists, user_id):
    db = get_db_connection()
    cursor = db.cursor()

    try:
        top_artist = []
        for index, artist in enumerate(top_artists["items"]):
            artist_id = artist["id"]
            artist_name = artist["name"]
            spotify_url = artist["external_urls"]["spotify"]
            followers = artist.get("followers", {}).get("total", 0)
            genres = ", ".join(artist.get("genres")) if artist.get("genres") else None
            image_url = artist["images"][0]["url"] if artist["images"] else None
            rank = index + 1
            uri = artist["uri"]

            top_artist.append((user_id, artist_id, artist_name, spotify_url, followers, genres, image_url, rank, uri))

        if top_artist:
            cursor.executemany("INSERT INTO users_top_artists (user_id, artist_id, artist_name, spotify_url, followers, genres, image_url, rank, uri) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (USER_ID, artist_id) DO UPDATE SET followers = EXCLUDED.followers, genres = EXCLUDED.genres, image_url = EXCLUDED.image_url", top_artist)
        else:
            print("No new top artists to add.")

        db.commit()

    except Exception as e:
        print(f"Database insertion error in top_artists_to_database: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()


def recents_to_database(recent_tracks, user_id):   
    db = get_db_connection()
    cursor = db.cursor()

    try:
        recent_records = []
        for item in recent_tracks.get("items", []):
            track = item.get("track", {})

            # Get duration_ms directly from the track object since it's already available
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

            # Add duration_ms to the record tuple
            recent_records.append((
                user_id, track_id, track_name, artist_id, artist_name, 
                album_name, album_image_url, played_at, duration_ms
            ))

        if recent_records:
            cursor.executemany(
                """
                INSERT INTO listening_history 
                (user_id, track_id, track_name, artist_id, artist_name, 
                album_name, album_image_url, played_at, duration_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, played_at) DO NOTHING
                """,
                recent_records
            )
            db.commit()
            print(f"Successfully inserted {len(recent_records)} records")
        else:
            print("No new tracks played.")

    except psycopg2.Error as e:
        print(f"Database error in recents_to_database: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()


def top_tracks_to_database(top_tracks, user_id):
    db = get_db_connection()
    cursor = db.cursor()

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
            release_date = track["album"]["release_date"]
            duration_ms = track["duration_ms"]
            is_explicit = track["explicit"]
            spotify_url = track["external_urls"]["spotify"]
            popularity = track["popularity"]
            rank = index + 1

            top_records.append((user_id, track_id, track_name, artist_id, artist_name, album_id, album_name, album_image_url, release_date, duration_ms, is_explicit, spotify_url, popularity, rank))

        if top_records:
            cursor.executemany("INSERT INTO top_tracks (user_id, track_id, track_name, artist_id, artist_name, album_id, album_name, album_image_url, release_date, duration_ms, is_explicit, spotify_url, popularity, rank) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (user_id, track_id) DO UPDATE SET rank = EXCLUDED.rank", top_records)
        else:
            print("There is no top tracks for this user")
        
        db.commit()

    except Exception as e:
        print(f"Database insertion error crud.py top_tracks_to_database: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()


async def all_albums_to_database(all_albums):
    db = get_db_connection()
    cursor = db.cursor()

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
            cursor.executemany("INSERT INTO albums (id, name, album_type, total_tracks, release_date, release_date_precision, restrictions_reason, spotify_url, image_url, uri, popularity, label, genres, external_isrc,external_ean, external_upc) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)  ON CONFLICT (uri) DO UPDATE SET popularity = EXCLUDED.popularity, genres = EXCLUDED.genres, image_url = EXCLUDED.image_url", tot_albums)
        else:
            print("No new albums to add.")
        
        db.commit()

    except Exception as e:
        print(f"Database insertion error: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()

def all_artists_to_database(top_artists):
    db = get_db_connection()
    cursor = db.cursor()


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
            cursor.executemany("INSERT INTO all_artists (artist_id, name, popularity, followers, genres, image_url, api_data) VALUES (%s, %s, %s, %s, %s, %s, %s)  ON CONFLICT (artist_id) DO UPDATE SET followers = EXCLUDED.followers, popularity = EXCLUDED.popularity, genres = EXCLUDED.genres, image_url = EXCLUDED.image_url", artist_records)
        else: 
            print("No artist here")
        db.commit()

    except Exception as e:
        print(f"Database insertion error: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()


def tracks_to_database(tracks):
    db = get_db_connection()
    cursor = db.cursor()

    try:
        track_records = []
        for track in tracks["items"]:
            # Debugging: Print the track dictionary
            print("Track dictionary:", track)

            track_id = track["id"]
            duration_ms = track["duration_ms"]


            track_records.append((track_id, duration_ms))

        if track_records:
            update_query = "UPDATE listening_history SET duration_ms = %s WHERE track_id = %s AND duration_ms IS NULL"
            update_data = [(record[1], record[0]) for record in track_records]
            cursor.executemany(update_query, update_data)
            db.commit()
        else:
            print("There is no top tracks for this user")
    except Exception as e:
        print(f"Database insertion error crud.py tracks_to_database: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()
