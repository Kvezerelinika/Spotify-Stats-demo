from datetime import datetime
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from collections import Counter

from app.spotify_api import get_top_artists, get_top_tracks, get_recently_played_tracks, get_now_playing
from app.crud import top_artists_to_database, top_tracks_to_database, recents_to_database
from app.database import get_db_connection

async def get_user_info(user_id, db):
    # Use asyncpg methods instead of cursor
    query = "SELECT * FROM users WHERE id = $1"
    return await db.fetchrow(query, user_id)



async def get_top_artists_db(user_id, db):
    query = "SELECT artist_name, image_url, spotify_url FROM users_top_artists WHERE user_id = $1 ORDER BY id ASC;"
    return await db.fetch(query, user_id)



async def get_top_tracks_db(user_id, db):
    query = "SELECT track_name, artist_name, popularity, album_image_url, spotify_url FROM top_tracks WHERE user_id = $1 ORDER BY rank ASC;"
    return await db.fetch(query, user_id)


async def get_track_play_counts(user_id, db):
    query = """
        SELECT track_name, artist_name, album_image_url, COUNT(*) AS track_play_counts
        FROM listening_history 
        WHERE user_id = $1 
        GROUP BY track_name, artist_name, album_image_url 
        ORDER BY track_play_counts DESC 
        LIMIT 10;
    """
    return await db.fetch(query, user_id)



async def get_daily_play_counts(user_id, db):
    query = """
        SELECT DATE(played_at) AS play_date, COUNT(*) AS daily_play_count
        FROM listening_history 
        WHERE user_id = $1 
        GROUP BY play_date 
        ORDER BY play_date DESC;
    """
    return await db.fetch(query, user_id)



async def get_total_play_count(user_id, db):
    query = "SELECT COUNT(*) FROM listening_history WHERE user_id = $1;"
    result = await db.fetchval(query, user_id)
    return result or 0


async def get_total_play_today(user_id, db):
    today = datetime.today().date()
    query = "SELECT COUNT(*) FROM listening_history WHERE user_id = $1 AND DATE(played_at) = $2;"
    result = await db.fetchval(query, user_id, today)
    return result or 0


async def get_current_playing(token):
    #cursor.execute("SELECT track_name, artist_name, album_image_url FROM listening_history WHERE user_id = %s ORDER BY played_at DESC LIMIT 1;", (user_id,))
    #data = cursor.fetchone()
    #return {"track_name": data[0], "artist_name": data[1], "album_image_url": data[2]} if data else {}

    # Return the data directly (FastAPI will handle the JSON conversion automatically)
    return await get_now_playing(token)  # ✅ FIXED: Returns the actual data


#SUM of the listening minutes and hours for entire history
async def get_total_listening_time(user_id, db):
    query = """
        SELECT SUM(duration_ms) 
        FROM listening_history 
        WHERE user_id = $1 AND duration_ms IS NOT NULL;
    """
    total_duration_ms = await db.fetchval(query, user_id) or 0
    return total_duration_ms // 60000, total_duration_ms // 3600000


#listening minutes and hours for today
async def get_total_listening_time_today(user_id, db):
    today = datetime.today().date()
    query = """
        SELECT SUM(duration_ms) 
        FROM listening_history 
        WHERE user_id = $1 AND DATE(played_at) = $2 AND duration_ms IS NOT NULL;
    """
    total_today_duration = await db.fetchval(query, user_id, today) or 0
    return total_today_duration // 60000, total_today_duration // 3600000

#listening minutes and hours for each day (grouped by day)
async def get_daily_listening_time(user_id, db):
    query = """
        SELECT DATE(played_at) AS play_date, 
               SUM(duration_ms)/60000 AS total_minutes, 
               SUM(duration_ms)/3600000 AS total_hours 
        FROM listening_history 
        WHERE user_id = $1 AND duration_ms IS NOT NULL 
        GROUP BY play_date 
        ORDER BY play_date DESC;
    """
    return await db.fetch(query, user_id)

# This is the existing code for the group_by_time_period function
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


# Ensure the data is passed correctly to your template (highlighted change)
async def complete_listening_history(user_id, db, limit, offset):
    query = """
        SELECT played_at, track_name, artist_name, duration_ms
        FROM listening_history 
        WHERE user_id = $1 
        ORDER BY played_at DESC 
        LIMIT $2 OFFSET $3;
    """
    records = await db.fetch(query, user_id, limit, offset)
    return group_by_time_period([dict(row) for row in records])  # Return grouped records by time period



async def get_top_genres(user_id, db):
    query = "SELECT genres FROM users_top_artists WHERE user_id = $1;"
    artist_genres = await db.fetch(query, user_id)

    genres_count = Counter()
    for row in artist_genres:
        genres = row["genres"].split(',') if row["genres"] else []
        genres_count.update(genres)

    top_genres = genres_count.most_common(5)
    return top_genres  # Return the list of tuples (genre, count)









async def get_last_update_from_db(user_id, data_type, time_range):
    db = await get_db_connection()  # Ensure this returns an asyncpg connection
    result = None  # Initialize result to avoid UnboundLocalError

    try:
        result = await db.fetchrow(
            """
            SELECT last_update 
            FROM user_data 
            WHERE user_id = $1 AND data_type = $2 AND time_range = $3;
            """,
            user_id, data_type, time_range
        )
    except Exception as e:
        print(f"Error fetching last update for {user_id}, {data_type}, {time_range}: {e}")
    finally:
        await db.close()  # Close connection properly

    return result["last_update"] if result else None




from datetime import datetime, timedelta

async def update_user_music_data(user_id, token, data_type, time_range=None):
    last_update = await get_last_update_from_db(user_id, data_type, time_range)
    current_time = datetime.now()

    # Define intervals for different data types and time ranges
    if data_type == "top_artists":
        interval = timedelta(weeks=12 if time_range == "long_term" else 6 if time_range == "medium_term" else 4)
    elif data_type == "top_tracks":
        interval = timedelta(days=1 if time_range == "short_term" else 7 if time_range == "medium_term" else 28)
    elif data_type == "recent_tracks":
        interval = timedelta(minutes=10)  # 10 minutes for recent tracks
    else:
        interval = timedelta(days=1)  # Default: 1 day

    # Check if data is outdated
    if not last_update or current_time - last_update > interval:
        print(f"Updating {data_type} data for user {user_id}, time range {time_range}...")

        if data_type == "top_artists":
            top_artists = await get_top_artists(token, time_range)
            await top_artists_to_database(top_artists, user_id, time_range)
        elif data_type == "top_tracks":
            top_tracks = await get_top_tracks(token)
            await top_tracks_to_database(top_tracks, user_id, time_range)
        elif data_type == "recent_tracks":
            recent_tracks = await get_recently_played_tracks(token)
            await recents_to_database(recent_tracks, user_id)

        # Update last update timestamp
        db = await get_db_connection()
        try:
            await db.execute(
                """
                INSERT INTO user_data (user_id, data_type, time_range, last_update)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, data_type, time_range) 
                DO UPDATE SET last_update = EXCLUDED.last_update;
                """,
                user_id, data_type, time_range, current_time
            )
        except Exception as e:
            print(f"Error updating last update timestamp: {e}")
        finally:
            await db.close()
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
