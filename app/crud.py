from app.database import get_db_connection
import json
from datetime import datetime

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
        print(f"Database insertion error: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()

def recents_to_database(recent_tracks, user_id):
    db = get_db_connection()
    cursor = db.cursor()

    try:
        recent_records = []
        for item in recent_tracks["items"]:
            track = item["track"]

            track_id = track["id"]
            track_name = track["name"]
            artist_id = track["artists"][0]["id"]
            artist_name = track["artists"][0]["name"]
            album_name = track["album"]["name"]
            album_image_url = track["album"]["images"][0]["url"] if track["album"]["images"] else None
            played_at = datetime.strptime(item["played_at"], "%Y-%m-%dT%H:%M:%S.%fZ")

            recent_records.append((user_id, track_id, track_name, artist_id, artist_name, album_name, album_image_url, played_at))

        if recent_records:
            cursor.executemany("INSERT INTO listening_history (user_id, track_id, track_name, artist_id, artist_name, album_name, album_image_url, played_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (played_at) DO NOTHING", recent_records)
        else:
            print("No tracks played yet")

        db.commit()

    except Exception as e:
        print(f"Database insertion error: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()

def top_tracks_to_database(top_tracks, user_id):
    db = get_db_connection()
    cursor = db.cursor()

    try:
        top_records = []
        for track in top_tracks["items"]:

            track_id = track["id"]
            track_name = track["name"]
            artist_id = track["artists"][0]["id"]
            artist_name = track["artists"][0]["name"]
            album_name = track["album"]["name"]
            album_image_url = track["album"]["images"][0]["url"] if track["album"]["images"] else None
            release_date = track["album"]["release_date"]
            duration_ms = track["duration_ms"]
            is_explicit = track["explicit"]
            spotify_url = track["external_urls"]["spotify"]

            top_records.append((user_id, track_id, track_name, artist_id, artist_name, album_name, album_image_url, release_date, duration_ms, is_explicit, spotify_url))

        if top_records:
            cursor.executemany("INSERT INTO top_tracks (user_id, track_id, track_name, artist_id, artist_name, album_name, album_image_url, release_date, duration_ms, is_explicit, spotify_url) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (track_id) DO NOTHING", top_records)
        else:
            print("There is no top tracks for this user")
        
        db.commit()

    except Exception as e:
        print(f"Database insertion error: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()


def all_albums_to_database(all_albums):
    db = get_db_connection()
    cursor = db.cursor()

    try:
        tot_albums = []
        for album in all_albums["items"]:

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

            tot_albums.append((name, album_type, total_tracks, release_date, release_date_precision, restrictions_reason, spotify_url, image_url, uri, popularity, label, genres, external_isrc, external_ean, external_upc))

        if tot_albums:
            cursor.executemany("INSERT INTO albums (name, album_type, total_tracks, release_date, release_date_precision, restrictions_reason, spotify_url, image_url, uri, popularity, label, genres, external_isrc,external_ean, external_upc) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)  ON CONFLICT (uri) DO UPDATE SET popularity = EXCLUDED.popularity, genres = EXCLUDED.genres, image_url = EXCLUDED.image_url", tot_albums)
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