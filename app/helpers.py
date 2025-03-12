from datetime import datetime
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse

from app.spotify_api import get_top_artists, get_top_tracks, get_recently_played_tracks, get_now_playing
from app.crud import top_artists_to_database, top_tracks_to_database, recents_to_database

def get_user_info(user_id, cursor):
    cursor.execute("SELECT images, display_name FROM users WHERE id = %s;", (user_id,))
    return cursor.fetchone()


def get_top_artists_db(user_id, cursor):
    cursor.execute("SELECT artist_name, image_url, spotify_url FROM users_top_artists WHERE user_id = %s ORDER BY id ASC;", (user_id,))
    return cursor.fetchall()


def get_top_tracks_db(user_id, cursor):
    cursor.execute("SELECT track_name, artist_name, popularity, album_image_url, spotify_url FROM top_tracks WHERE user_id = %s ORDER BY rank ASC;", (user_id,))
    return cursor.fetchall()


def get_track_play_counts(user_id, cursor):
    cursor.execute("""SELECT track_name, artist_name, album_image_url, COUNT(*) AS track_play_counts FROM listening_history WHERE user_id = %s GROUP BY track_name, artist_name, album_image_url ORDER BY track_play_counts DESC LIMIT 10;""", (user_id,))
    return cursor.fetchall()


def get_daily_play_counts(user_id, cursor):
    cursor.execute("""SELECT DATE(played_at) AS play_date, COUNT(*) AS daily_play_count FROM listening_history WHERE user_id = %s GROUP BY play_date ORDER BY play_date DESC;""", (user_id,))
    return cursor.fetchall()


def get_total_play_count(user_id, cursor):
    cursor.execute("SELECT COUNT(*) FROM listening_history WHERE user_id = %s;", (user_id,))
    return cursor.fetchone()[0] or 0


def get_total_play_today(user_id, cursor):
    today = datetime.today().date()
    cursor.execute("SELECT COUNT(*) FROM listening_history WHERE user_id = %s AND DATE(played_at) = %s;", (user_id, today))
    return cursor.fetchone()[0] or 0


async def get_current_playing(token):
    #cursor.execute("SELECT track_name, artist_name, album_image_url FROM listening_history WHERE user_id = %s ORDER BY played_at DESC LIMIT 1;", (user_id,))
    #data = cursor.fetchone()
    #return {"track_name": data[0], "artist_name": data[1], "album_image_url": data[2]} if data else {}

    # Get the current track and artist data from the Spotify API
    now_playing_data = await get_now_playing(token)

    # Return the data directly (FastAPI will handle the JSON conversion automatically)
    return now_playing_data


def get_total_listening_time(user_id, cursor):
    cursor.execute("SELECT SUM(duration_ms) FROM listening_history WHERE user_id = %s AND duration_ms IS NOT NULL;", (user_id,))
    total_duration_ms = cursor.fetchone()[0] or 0
    return total_duration_ms // 60000, total_duration_ms // 3600000


def get_daily_listening_time(user_id, cursor):
    cursor.execute("""SELECT DATE(played_at), SUM(duration_ms)/60000, SUM(duration_ms)/3600000 FROM listening_history WHERE user_id = %s AND duration_ms IS NOT NULL GROUP BY play_date ORDER BY play_date DESC;""", (user_id,))
    return cursor.fetchall()


def get_top_genres(user_id, cursor):
    genres_count = {}
    cursor.execute("""SELECT genres FROM users_top_artists WHERE user_id = %s;""", (user_id,))
    artist_genres = cursor.fetchall()  # List of tuples, e.g., [("rock, pop",), ("jazz",), ("pop, hip-hop",)]

    for row in artist_genres:
        genre_list = row[0].split(", ")  # Convert "rock, pop" → ["rock", "pop"]
        for genre in genre_list:
            genres_count[genre] = genres_count.get(genre, 0) + 1
    # Sort by count (highest first) and take top 20
    top_genres = sorted(genres_count.items(), key=lambda x: x[1], reverse=True)[:20]
    return top_genres


async def update_user_music_data(token, user_id):
    try:
        # top artists
        top_artists = await get_top_artists(token)
        top_artists_to_database(top_artists, user_id)

        # top tracks
        top_tracks = await get_top_tracks(token)
        top_tracks_to_database(top_tracks, user_id)

        # recent tracks
        recent_tracks = await get_recently_played_tracks(token)
        recents_to_database(recent_tracks, user_id)

    except Exception as e:
        print(f"Error updating music data: {e}")
        # Handle the exception (maybe log it or notify the user)
