from datetime import datetime, timedelta
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from collections import Counter
from sqlalchemy import text

from app.spotify_api import SpotifyClient
from app.crud import SpotifyDataSaver
from app.database import get_db_connection

import pytz, logging

class MusicDataService:
    def __init__(self, user_id, db):
        self.user_id = user_id
        self.db = db

    async def get_user_info(self):
        try:
            query = text("SELECT * FROM users WHERE user_id = :user_id")
            result = await self.db.execute(query, {"user_id": self.user_id})
            row = result.fetchone() 
            return dict(row._mapping) if row else None
        except Exception as e:
            logging.error(f"[DB] Error fetching user info for user_id={self.user_id}: {e}")
            return None

    async def get_top_artists_db(self, time_range):
        query = text("""
            SELECT a.name, a.image_url, a.spotify_url, uta.rank
            FROM users_top_artists uta
            JOIN artists a ON uta.artist_id = a.artist_id
            WHERE uta.user_id = :user_id AND uta.time_range = :time_range
            ORDER BY uta.rank ASC;
        """)
        result = await self.db.execute(query, {
            "user_id": self.user_id,
            "time_range": time_range
        })
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]

    async def get_top_tracks_db(self, time_range):
        query = text ("""
            SELECT t.name, a.name AS artist_name, t.album_image_url, t.spotify_url, utt.rank
            FROM users_top_tracks utt
            JOIN tracks t ON utt.track_id = t.track_id
            JOIN artists a ON t.artist_id = a.artist_id
            WHERE utt.user_id = :user_id AND utt.time_range = :time_range
            ORDER BY utt.rank ASC;
        """)
        result = await self.db.execute(query, {"user_id": self.user_id, "time_range": time_range})
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]

    async def get_track_play_counts(self):
        query = text("""
            SELECT t.name, t.artist_name, t.album_image_url, COUNT(*) AS track_play_counts
            FROM listening_history lh 
            JOIN tracks t ON lh.track_id = t.track_id
            WHERE lh.user_id = :user_id
            GROUP BY t.name, t.artist_name, t.album_image_url 
            ORDER BY track_play_counts DESC 
            LIMIT 10;
        """)
        result = await self.db.execute(query, {"user_id": self.user_id})
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]

    async def get_daily_play_counts(self):
        query = text("""
            SELECT DATE(lh.played_at) AS play_date, COUNT(*) AS daily_play_count
            FROM listening_history lh
            WHERE lh.user_id = :user_id
            GROUP BY play_date
            ORDER BY play_date DESC;
        """)
        result = await self.db.execute(query, {"user_id": self.user_id})
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]

    async def get_total_play_today(self):
        today = datetime.today().date()
        query = text("""SELECT COUNT(*) FROM listening_history WHERE user_id = :user_id AND DATE(played_at) = :today;""")
        result = await self.db.scalar(query, {"user_id": self.user_id, "today": today})
        return result or 0

    async def get_total_play_count(self):
        query = text("""SELECT COUNT(*) FROM listening_history WHERE user_id = :user_id;""")
        result = await self.db.scalar(query, {"user_id": self.user_id})
        return result or 0

    async def get_total_listening_time(self):
        query = text("""
            SELECT SUM(t.duration_ms)
            FROM listening_history lh
            JOIN tracks t ON lh.track_id = t.track_id
            WHERE lh.user_id = :user_id AND t.duration_ms IS NOT NULL;
        """)
        result = await self.db.execute(query, {"user_id": self.user_id})
        total_ms = result.scalar() or 0
        return total_ms // 60000, total_ms // 3600000

    async def get_total_listening_time_today(self):
        today = datetime.today().date()
        query = text("""
            SELECT SUM(t.duration_ms)
            FROM listening_history lh
            JOIN tracks t ON lh.track_id = t.track_id
            WHERE lh.user_id = :user_id AND DATE(lh.played_at) = :today AND t.duration_ms IS NOT NULL;
        """)
        result = await self.db.execute(query, {"user_id": self.user_id, "today": today})
        total_ms = result.scalar() or 0
        return total_ms // 60000, total_ms // 3600000

    async def get_daily_listening_time(self):
        query = text("""
            SELECT DATE(lh.played_at) AS play_date,
                SUM(t.duration_ms) / 60000 AS total_minutes
            FROM listening_history lh
            JOIN tracks t ON lh.track_id = t.track_id
            WHERE lh.user_id = :user_id AND t.duration_ms IS NOT NULL
            GROUP BY play_date
            ORDER BY play_date DESC;
        """)
        result = await self.db.execute(query, {"user_id": self.user_id})
        rows = result.all()
        return [{"play_date": row[0], "total_minutes": row[1], "total_hours": row[2]} for row in rows]

    async def complete_listening_history(self, limit, offset):
        query = text("""
            SELECT lh.played_at, t.name, t.artist_name, t.duration_ms
            FROM listening_history lh
            JOIN tracks t ON lh.track_id = t.track_id
            WHERE lh.user_id = :user_id
            ORDER BY lh.played_at DESC 
            LIMIT :limit OFFSET :offset;
        """)
        result = await self.db.execute(query, {
            "user_id": self.user_id,
            "limit": limit,
            "offset": offset
        })
        rows = result.mappings().all()
        return self.group_by_time_period(rows)

    def group_by_time_period(self, records):
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        start_of_week = today_start - timedelta(days=today_start.weekday())
        start_of_last_week = start_of_week - timedelta(weeks=1)
        end_of_last_week = start_of_week - timedelta(days=1)
        start_of_this_month = today_start.replace(day=1)
        end_of_this_month = (start_of_this_month.replace(month=now.month % 12 + 1, day=1) - timedelta(days=1))

        time_groups = {"Today": [], "Yesterday": [], "This Week": [], "This Month": [], "Older": []}

        for track in records:
            played_at = track['played_at']
            if isinstance(played_at, str):
                played_at = datetime.fromisoformat(played_at)

            if played_at.date() == today_start.date():
                time_groups["Today"].append(track)
            elif played_at.date() == yesterday_start.date():
                time_groups["Yesterday"].append(track)
            elif start_of_week <= played_at < today_start:
                time_groups["This Week"].append(track)
            elif start_of_last_week <= played_at <= end_of_last_week:
                if not (start_of_this_month <= played_at <= end_of_this_month):
                    time_groups["This Week"].append(track)
                else:
                    time_groups["Older"].append(track)
            elif start_of_this_month <= played_at <= end_of_this_month:
                time_groups["This Month"].append(track)
            else:
                time_groups["Older"].append(track)

        return time_groups

    async def get_top_genres(self):
        query = text("""
            SELECT a.genres
            FROM listening_history lh
            JOIN tracks t ON lh.track_id = t.track_id
            JOIN artists a ON t.artist_id = a.artist_id
            WHERE lh.user_id = :user_id;
        """)
        result = await self.db.execute(query, {"user_id": self.user_id})
        rows = result.mappings().all()

        genres_count = Counter()
        for row in rows:
            genres = row["genres"] or []
            genres_count.update(genres)

        return genres_count.most_common(5)



class UserMusicUpdater:
    def __init__(self, db, user_id, token):
        self.db = db
        self.user_id = user_id
        self.token = token

    async def get_last_update(self, data_type, time_range):
        result = None
        try:
            if data_type == "top_tracks":
                query = text("""
                    SELECT last_updated
                    FROM users_top_tracks
                    WHERE user_id = :user_id AND time_range = :time_range;
                """)
                row = await self.db.execute(query, {
                    "user_id": self.user_id,
                    "time_range": time_range
                })
                result = row.scalar()

            elif data_type == "top_artists":
                query = text("""
                    SELECT last_updated 
                    FROM users_top_artists 
                    WHERE user_id = :user_id AND time_range = :time_range;
                """)
                row = await self.db.execute(query, {
                    "user_id": self.user_id,
                    "time_range": time_range
                })
                result = row.scalar()

            elif data_type == "recent_tracks":
                query = text("""
                    SELECT MAX(played_at) as last_updated
                    FROM listening_history 
                    WHERE user_id = :user_id;
                """)
                row = await self.db.execute(query, {
                    "user_id": self.user_id
                })
                result = row.scalar()

        except Exception as e:
            logging.error(f"[DB] Error fetching last update for user={self.user_id}, type={data_type}, range={time_range}: {e}")
        
        return result

    async def update_data_if_needed(self, data_type, time_range):
        last_update = await self.get_last_update(data_type, time_range)
        print(f"Last update for {self.user_id}, {data_type}, {time_range}: {last_update}")

        if last_update and last_update.tzinfo is None:
            last_update = pytz.UTC.localize(last_update)

        current_time = datetime.utcnow().replace(tzinfo=pytz.UTC)
        print(f"Current time: {current_time}")

        intervals = {
            "top_artists": timedelta(weeks=12 if time_range == "long_term" else 6 if time_range == "medium_term" else 4),
            "top_tracks": timedelta(days=1 if time_range == "short_term" else 7 if time_range == "medium_term" else 28),
            "recent_tracks": timedelta(minutes=50),
        }

        interval = intervals[data_type]
        print(f"Interval for {data_type}: {interval}")

        if not last_update or current_time - last_update > interval:
            logging.info(f"Fetching new {data_type} data for user {self.user_id}...")

            async with SpotifyDataSaver(self.token, self.user_id) as saver:
                client = SpotifyClient(self.token)
                if data_type == "top_artists":
                    data = await client.get_top_artists(time_range)
                    await saver.top_artists_to_database(data, time_range, current_time)

                elif data_type == "top_tracks":
                    data = await client.get_top_tracks(time_range)
                    await saver.top_tracks_to_database(data, time_range)

                elif data_type == "recent_tracks":
                    data = await client.get_recently_played_tracks()
                    await saver.recents_to_database(data)

        else:
            logging.info(f"{data_type} for user {self.user_id}, range {time_range} is up to date.")













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
