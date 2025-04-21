from datetime import datetime, timedelta
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from collections import Counter

from app.spotify_api import get_top_artists, get_top_tracks, get_recently_played_tracks, get_now_playing
from app.crud import SpotifyDataSaver
from app.database import get_db_connection

class UserMusicDataService:
    def __init__(self, user_id: str, db):
        self.user_id = user_id
        self.db = db

    async def get_top_tracks(self, time_range: str = "short_term"):
        query = """
        SELECT track_name, artist_name, play_count
        FROM top_tracks
        WHERE user_id = %s AND time_range = %s
        ORDER BY play_count DESC
        LIMIT 10
        """
        cursor = await self.db.execute(query, (self.user_id, time_range))
        result = await cursor.fetchall()
        return result

    async def get_top_artists(self, time_range: str = "short_term"):
        query = """
        SELECT artist_name, play_count
        FROM top_artists
        WHERE user_id = %s AND time_range = %s
        ORDER BY play_count DESC
        LIMIT 10
        """
        cursor = await self.db.execute(query, (self.user_id, time_range))
        result = await cursor.fetchall()
        return result

    async def get_top_albums(self, time_range: str = "short_term"):
        query = """
        SELECT album_name, artist_name, play_count
        FROM top_albums
        WHERE user_id = %s AND time_range = %s
        ORDER BY play_count DESC
        LIMIT 10
        """
        cursor = await self.db.execute(query, (self.user_id, time_range))
        result = await cursor.fetchall()
        return result

    async def get_total_play_count(self):
        query = """
        SELECT SUM(play_count) as total
        FROM top_tracks
        WHERE user_id = %s
        """
        cursor = await self.db.execute(query, (self.user_id,))
        result = await cursor.fetchone()
        return result["total"] if result and result["total"] else 0

    async def get_favorite_genres(self):
        query = """
        SELECT genre, SUM(play_count) as total
        FROM top_artists
        WHERE user_id = %s
        GROUP BY genre
        ORDER BY total DESC
        LIMIT 5
        """
        cursor = await self.db.execute(query, (self.user_id,))
        result = await cursor.fetchall()
        return result






"""
async def get_user_info(user_id, db):
    # Use asyncpg methods instead of cursor
    query = "SELECT * FROM users WHERE user_id = $1"
    return await db.fetchrow(query, user_id)



async def get_top_artists_db(user_id, db, time_range):
    query = """
        SELECT 
            a.name, 
            a.image_url, 
            a.spotify_url,
            uta.rank
        FROM users_top_artists uta
        JOIN artists a ON uta.artist_id = a.artist_id
        WHERE uta.user_id = $1 
        AND uta.time_range = $2
        ORDER BY uta.rank ASC;
    """
    return await db.fetch(query, user_id, time_range)



"""from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import UsersTopArtists, Artist  # Adjust your import path as needed

async def get_top_artists_db(user_id: str, db: AsyncSession, time_range: str):
    result = await db.execute(
        select(UsersTopArtists)
        .options(joinedload(UsersTopArtists.artists))  # eager load artist
        .where(
            UsersTopArtists.user_id == user_id,
            UsersTopArtists.time_range == time_range
        )
        .order_by(UsersTopArtists.rank)
    )

    top_artists = result.scalars().all()

    return [
        {
            "name": artist.artists.name,
            "image_url": artist.artists.image_url,
            "spotify_url": artist.artists.spotify_url,
            "rank": artist.rank
        }
        for artist in top_artists
    ]"""






async def get_top_tracks_db(user_id, db, time_range):
    query = """
        SELECT 
            t.name,                -- Track name
            a.name AS artist_name, -- Artist name
            t.album_image_url,     -- Album image URL
            t.spotify_url,         -- Spotify URL
            utt.rank               -- Rank
        FROM users_top_tracks utt
        JOIN tracks t ON utt.track_id = t.track_id
        JOIN artists a ON t.artist_id = a.artist_id
        WHERE utt.user_id = $1 AND utt.time_range = $2
        ORDER BY utt.rank ASC;
    """
    return await db.fetch(query, user_id, time_range)



async def get_track_play_counts(user_id, db):
    query = """
        SELECT 
            t.name, 
            t.artist_name, 
            t.album_image_url, 
            COUNT(*) AS track_play_counts
        FROM listening_history lh 
        JOIN tracks t ON lh.track_id = t.track_id
        WHERE lh.user_id = $1 
        GROUP BY t.name, t.artist_name, t.album_image_url 
        ORDER BY track_play_counts DESC 
        LIMIT 10;
    """
    return await db.fetch(query, user_id)



async def get_daily_play_counts(user_id, db):
    query = """
        SELECT 
            DATE(lh.played_at) AS play_date, 
            COUNT(*) AS daily_play_count
        FROM listening_history lh
        WHERE lh.user_id = $1
        GROUP BY play_date
        ORDER BY play_date DESC;
    """
    return await db.fetch(query, user_id)

async def get_total_play_today(user_id, db):
    today = datetime.today().date()
    query = "SELECT COUNT(*) FROM listening_history WHERE user_id = $1 AND DATE(played_at) = $2;"
    result = await db.fetchval(query, user_id, today)
    return result or 0


async def get_total_play_count(user_id, db):
    query = "SELECT COUNT(*) FROM listening_history WHERE user_id = $1;"
    result = await db.fetchval(query, user_id)
    return result or 0


#SUM of the listening minutes and hours for entire history
async def get_total_listening_time(user_id, db):
    query = """
        SELECT SUM(t.duration_ms) 
        FROM listening_history lh
        JOIN tracks t ON lh.track_id = t.track_id
        WHERE lh.user_id = $1 AND t.duration_ms IS NOT NULL;
    """
    total_duration_ms = await db.fetchval(query, user_id) or 0
    
    # Convert milliseconds to minutes and hours
    total_minutes = total_duration_ms // 60000
    total_hours = total_duration_ms // 3600000
    
    return total_minutes, total_hours



async def get_current_playing(token):
    #cursor.execute("SELECT track_name, artist_name, album_image_url FROM listening_history WHERE user_id = %s ORDER BY played_at DESC LIMIT 1;", (user_id,))
    #data = cursor.fetchone()
    #return {"track_name": data[0], "artist_name": data[1], "album_image_url": data[2]} if data else {}

    # Return the data directly (FastAPI will handle the JSON conversion automatically)
    return await get_now_playing(token)  # ✅ FIXED: Returns the actual data






#listening minutes and hours for today
async def get_total_listening_time_today(user_id, db):
    today = datetime.today().date()
    query = """
        SELECT SUM(t.duration_ms) 
        FROM listening_history lh
        JOIN tracks t ON lh.track_id = t.track_id
        WHERE lh.user_id = $1 AND DATE(lh.played_at) = $2 AND t.duration_ms IS NOT NULL;
    """
    total_today_duration = await db.fetchval(query, user_id, today) or 0
    return total_today_duration // 60000, total_today_duration // 3600000


#listening minutes and hours for each day (grouped by day)
async def get_daily_listening_time(user_id, db):
    query = """
        SELECT DATE(lh.played_at) AS play_date, 
               SUM(t.duration_ms) / 60000 AS total_minutes, 
               SUM(t.duration_ms) / 3600000 AS total_hours 
        FROM listening_history lh
        JOIN tracks t ON lh.track_id = t.track_id
        WHERE lh.user_id = $1 AND t.duration_ms IS NOT NULL
        GROUP BY play_date
        ORDER BY play_date DESC;
    """
    return await db.fetch(query, user_id)





def group_by_time_period(records):
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    start_of_week = today_start - timedelta(days=today_start.weekday())  # Monday of this week
    start_of_last_week = start_of_week - timedelta(weeks=1)
    end_of_last_week = start_of_week - timedelta(days=1)
    start_of_this_month = today_start.replace(day=1)
    end_of_this_month = (start_of_this_month.replace(month=now.month % 12 + 1, day=1) - timedelta(days=1))

    time_groups = {
        "Today": [],
        "Yesterday": [],
        "This Week": [],
        "This Month": [],
        "Older": [],
    }

    for track in records:
        played_at = track['played_at']
        # Normalize played_at to a datetime object if needed
        if isinstance(played_at, str):
            played_at = datetime.fromisoformat(played_at)  # Convert if it's a string
        
        if played_at.date() == today_start.date():
            time_groups["Today"].append(track)
        elif played_at.date() == yesterday_start.date():
            time_groups["Yesterday"].append(track)
        elif start_of_week <= played_at < today_start:
            time_groups["This Week"].append(track)
        elif start_of_last_week <= played_at <= end_of_last_week:
            # Only add to "Last Week" if it doesn't fall within the current month's range
            if not (start_of_this_month <= played_at <= end_of_this_month):
                time_groups["This Week"].append(track)  # This week is handled in "This Month"
            else:
                time_groups["Older"].append(track)
        elif start_of_this_month <= played_at <= end_of_this_month:
            time_groups["This Month"].append(track)
        else:
            time_groups["Older"].append(track)
    
    return time_groups



# Ensure the data is passed correctly to your template (highlighted change)
async def complete_listening_history(user_id, db, limit, offset):
    query = """
        SELECT lh.played_at, t.name, t.artist_name, t.duration_ms
        FROM listening_history lh
        JOIN tracks t ON lh.track_id = t.track_id
        WHERE lh.user_id = $1 
        ORDER BY lh.played_at DESC 
        LIMIT $2 OFFSET $3;
    """
    records = await db.fetch(query, user_id, limit, offset)
    return group_by_time_period([dict(row) for row in records])  # Return grouped records by time period




async def get_top_genres(user_id, db):
    query = """
        SELECT a.genres
        FROM listening_history lh
        JOIN tracks t ON lh.track_id = t.track_id
        JOIN artists a ON t.artist_id = a.artist_id
        WHERE lh.user_id = $1;
    """
    artist_genres = await db.fetch(query, user_id)

    genres_count = Counter()
    for row in artist_genres:
        genres = row["genres"] if row["genres"] else []
        genres_count.update(genres)

    top_genres = genres_count.most_common(5)
    return top_genres  # Return the list of tuples (genre, count)










async def get_last_update_from_db(user_id, data_type, time_range):
    db = await get_db_connection()  # Ensure this returns an asyncpg connection
    result = None  # Initialize result

    try:
        if data_type == "top_tracks":
            result = await db.fetchrow(
                """
                SELECT last_updated  -- Column name is last_updated, not last_update
                FROM users_top_tracks
                WHERE user_id = $1 AND time_range = $2;
                """,
                user_id, time_range  # Fix: Use time_range instead of data_type
            )
            return result["last_updated"] if result else None  # Fix KeyError

        elif data_type == "top_artists":   
            result = await db.fetchrow(
                """
                SELECT last_updated 
                FROM users_top_artists 
                WHERE user_id = $1 AND time_range = $2;
                """,
                user_id, time_range
            )
            return result["last_updated"] if result else None  # Fix KeyError

        elif data_type == "recent_tracks":
            result = await db.fetchrow(
                """
                SELECT MAX(played_at) as last_updated  -- Use MAX() to get the most recent track
                FROM listening_history 
                WHERE user_id = $1;
                """,
                user_id
            )
            return result["last_updated"] if result else None  # Fix KeyError

    except Exception as e:
        print(f"Error fetching last update for {user_id}, {data_type}, {time_range}: {e}")
        return None  # Return None on error
    finally:
        await db.close()  # Close connection properly


import pytz
from datetime import datetime, timedelta
import logging

async def update_user_music_data(user_id, token, data_type, time_range):
    # Fetch last update from DB
    last_update = await get_last_update_from_db(user_id, data_type, time_range)
    print(f"Last update for {user_id}, {data_type}, {time_range}: {last_update}")

    # Convert last_update to UTC if it's naive
    if last_update and last_update.tzinfo is None:
        last_update = pytz.UTC.localize(last_update)

    # Ensure current time is in UTC
    current_time = datetime.utcnow().replace(tzinfo=pytz.UTC)
    print(f"Current time: {current_time}")

    # Define update intervals based on data_type
    intervals = {
        "top_artists": timedelta(weeks=12 if time_range == "long_term" else 6 if time_range == "medium_term" else 4),
        "top_tracks": timedelta(days=1 if time_range == "short_term" else 7 if time_range == "medium_term" else 28),
        "recent_tracks": timedelta(minutes=50),
    }

    interval = intervals[data_type]
    print(f"Interval for {data_type}: {interval}")

    if not last_update or current_time - last_update > interval:
        logging.info(f"Updating {data_type} data for user {user_id}, time range {time_range}...")

        async with SpotifyDataSaver(token, user_id) as saver:
            if data_type == "top_artists":
                top_artists_data = await get_top_artists(token, time_range)
                await saver.top_artists_to_database(top_artists_data, time_range, current_time)

            elif data_type == "top_tracks":
                top_tracks_data = await get_top_tracks(token, time_range)
                await saver.top_tracks_to_database(top_tracks_data, time_range)

            elif data_type == "recent_tracks":
                recent_tracks_data = await get_recently_played_tracks(token)
                await saver.recents_to_database(recent_tracks_data)

    else:
        logging.info(f"{data_type} data for user {user_id}, time range {time_range} is up-to-date.")

"""









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
