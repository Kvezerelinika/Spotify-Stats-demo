from datetime import datetime
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse

from app.spotify_api import get_top_artists, get_top_tracks, get_recently_played_tracks, get_now_playing
from app.crud import top_artists_to_database, top_tracks_to_database, recents_to_database
from app.database import get_db_connection

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


#SUM of the listening minutes and hours for entire history
def get_total_listening_time(user_id, cursor):
    cursor.execute("SELECT SUM(duration_ms) FROM listening_history WHERE user_id = %s AND duration_ms IS NOT NULL;", (user_id,))
    total_duration_ms = cursor.fetchone()[0] or 0
    return total_duration_ms // 60000, total_duration_ms // 3600000

#listening minutes and hours for today
def get_total_listening_time_today(user_id, cursor):
    today = datetime.today().date()
    cursor.execute("SELECT SUM(duration_ms) FROM listening_history WHERE user_id = %s AND DATE(played_at) AND duration_ms NOT NULL;", (user_id, today))
    total_today_duration = cursor.fetchone()[0] or 0
    return total_today_duration // 60000, total_today_duration // 3600000

#listening minutes and hours for each day (grouped by day)
def get_daily_listening_time(user_id, cursor):
    cursor.execute("""SELECT DATE(played_at), SUM(duration_ms)/60000, SUM(duration_ms)/3600000 FROM listening_history WHERE user_id = %s AND duration_ms IS NOT NULL GROUP BY play_date ORDER BY play_date DESC;""", (user_id,))
    return cursor.fetchall()

def complete_listening_history(user_id, cursor, limit=100, offset=0):
    cursor.execute("""SELECT track_name, artist_name, album_name, album_image_url, played_at FROM listening_history WHERE user_id = %s ORDER BY played_at DESC LIMIT %s OFFSET %s""", (user_id, limit, offset))
    return cursor.fetchall()

def group_by_time_period(records):
    now = datetime.now()
    time_groups = {
        "Today": [],
        "Yesterday": [],
        "This Week": [],
        "Last Week": [],
        "This Month": [],
        "Older": [],
    }

    for track in records:
        played_at = track['played_at']
        delta = now - played_at

        if delta.days == 0:
            time_groups["Today"].append(track)
        elif delta.days == 1:
            time_groups["Yesterday"].append(track)
        elif delta.days <= 7:
            time_groups["This Week"].append(track)
        elif delta.days <= 14:
            time_groups["Last Week"].append(track)
        elif played_at.month == now.month:
            time_groups["This Month"].append(track)
        else:
            time_groups["Older"].append(track)
    
    return time_groups

def complete_listening_history(user_id, cursor, limit=100, offset=0):
    cursor.execute("""
        SELECT track_name, artist_name, album_name, album_image_url, played_at
        FROM listening_history
        WHERE user_id = %s
        ORDER BY played_at DESC
        LIMIT %s OFFSET %s
    """, (user_id, limit, offset))
    
    records = cursor.fetchall()
    grouped_records = group_by_time_period(records)
    return grouped_records


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










async def get_last_update_from_db(user_id, data_type, time_range):
    db = get_db_connection()
    cursor = db.cursor()

    # Query the last update timestamp for the specified data_type and time_range
    cursor.execute("""
        SELECT last_update 
        FROM user_data 
        WHERE user_id = %s AND data_type = %s AND time_range = %s;
    """, (user_id, data_type, time_range))

    result = cursor.fetchone()
    cursor.close()
    db.close()

    if result:
        return result[0]  # Return the last update timestamp
    return None  # No record, need to fetch fresh data



from datetime import datetime, timedelta

async def update_user_music_data(user_id, token, data_type, time_range=None):
    last_update = await get_last_update_from_db(user_id, data_type, time_range)
    current_time = datetime.now()

    # Define intervals for different data types and time ranges
    if data_type == "top_artists":
        if time_range == "long_term":
            interval = timedelta(weeks=4 * 12)  # 1 month
        elif time_range == "medium_term":
            interval = timedelta(weeks=4 * 6)  # 1 week
        elif time_range == "short_term":
            interval = timedelta(weeks=4)  # 1 week
    elif data_type == "top_tracks":
        if time_range == "short_term":
            interval = timedelta(days=1)  # 1 day
        elif time_range == "medium_term":
            interval = timedelta(weeks=1)  # 1 week
        else:
            interval = timedelta(weeks=4)  # 1 month
    elif data_type == "recent_tracks":
        interval = timedelta(hours=1)  # 1 hour for recent tracks
    else:
        interval = timedelta(days=1)  # Default: 1 day

    # Check if data is outdated based on the defined interval
    if not last_update or current_time - last_update > interval:
        print(f"Updating {data_type} data for user {user_id}, time range {time_range}...")

        # Fetch and insert/update the appropriate data
        if data_type == "top_artists":
            top_artists = await get_top_artists(token, time_range)
            top_artists_to_database(top_artists, user_id, time_range)
        elif data_type == "top_tracks":
            top_tracks = await get_top_tracks(token)
            top_tracks_to_database(top_tracks, user_id, time_range)
        elif data_type == "recent_tracks":
            recent_tracks = await get_recently_played_tracks(token)
            recents_to_database(recent_tracks, user_id)

        # Update the last update timestamp in the database
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO user_data (user_id, data_type, time_range, last_update)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, data_type, time_range) 
            DO UPDATE SET last_update = EXCLUDED.last_update;
        """, (user_id, data_type, time_range, current_time))
        db.commit()
        cursor.close()
        db.close()
    else:
        print(f"{data_type} data for user {user_id}, time range {time_range} is up-to-date.")




"""async def update_user_music_data(token, user_id):
    try:
        # top artists
        #top_artists = await get_top_artists(token)
        #top_artists_to_database(top_artists, user_id)

        #long term top artists
        top_artists_long_term = await get_top_artists(token, "long_term")
        top_artists_to_database(top_artists_long_term, user_id)

        #medium term top artists
        top_artists_medium_term = await get_top_artists(token, "medium_term")
        top_artists_to_database(top_artists_medium_term, user_id)

        #short term top artists
        top_artists_short_term = await get_top_artists(token, "short_term")
        top_artists_to_database(top_artists_short_term, user_id)


        # top tracks
        top_tracks = await get_top_tracks(token)
        top_tracks_to_database(top_tracks, user_id)

        # recent tracks
        recent_tracks = await get_recently_played_tracks(token)
        recents_to_database(recent_tracks, user_id)

    except Exception as e:
        print(f"Error updating music data: {e}")
        # Handle the exception (maybe log it or notify the user)"""
