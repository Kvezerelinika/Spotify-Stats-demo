from database import get_db_connection
import json

def top_artists_to_database(top_artists):
    db = get_db_connection()
    cursor = db.cursor()


    try:
        artist_records = []
        for index, artist in enumerate(top_artists["items"]):
            artist_id = artist["id"]
            name = artist["name"]
            rank = index + 1
            followers = artist["followers"]["total"]
            genres = ", ".join(artist["genres"]) if artist["genres"] else None
            image_url = artist["images"][0]["url"] if artist["images"] else None
            api_data = json.dumps(artist)

            artist_records.append((artist_id, name, rank, followers, genres, image_url, api_data))

        cursor.executemany("INSERT INTO top_artists (artist_id, name, rank, followers, genres, image_url, api_data) VALUES (%s, %s, %s, %s, %s, %s, %s)", artist_records)
        db.commit()

    except Exception as e:
        print(f"Database insertion error: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()

        
def recents_to_database(recent_tracks):
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
            played_at = item["played_at"]

            recent_records.append((track_id, track_name, artist_id, artist_name, album_name, album_image_url, played_at))

        cursor.executemany("INSERT INTO listening_history (track_id, track_name, artist_id, artist_name, album_name, album_image_url, played_at) VALUES (%s, %s, %s, %s, %s, %s, %s)", recent_records)
        db.commit()

    except Exception as e:
        print(f"Database insertion error: {e}")
        db.rollback()
    
    finally:
        cursor.close()
        db.close()