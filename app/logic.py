# logic.py
from sqlalchemy import select, func, Integer, cast
from sqlalchemy.engine import Row
from datetime import date
from app.db import User, Track, Album, Artist, ListeningHistory


class LogicHandlers:

    @staticmethod
    async def get_user_profile_logic(user_id: str, db) -> Row | None:
        stmt = select(
            User.user_id,
            User.image_url,
            User.display_name,
            User.custom_username,
            User.bio,
            User.preferred_language,
            User.timezone
        ).where(User.user_id == user_id)

        result = await db.execute(stmt)
        return result.one_or_none()

    @staticmethod
    async def get_track_details_logic(track_id: str, db) -> Row | None:
        stmt = select(
            Track.track_id,
            Track.name,
            Track.album_id,
            Track.artist_id,
            Track.artist_name,
            Track.spotify_url,
            Track.duration_ms,
            Track.popularity,
            Track.explicit,
            Track.track_number,
            Track.album_release_date,
            Track.album_image_url,
            Track.album_name
        ).where(Track.track_id == track_id)

        result = await db.execute(stmt)
        return result.one_or_none()

    @staticmethod
    async def get_album_details_logic(album_id: str, db) -> Row | None:
        stmt = (
            select(
                Album.album_id,
                Album.name.label("album_name"),
                Album.release_date,
                Album.image_url,
                Album.spotify_url,
                Album.total_tracks,
                Artist.artist_id,
                Artist.name.label("artist_name")
            )
            .join(Artist, Album.artist_id == Artist.artist_id)
            .where(Album.album_id == album_id)
        )

        result = await db.execute(stmt)
        return result.one_or_none()

    @staticmethod
    async def get_artist_details_logic(artist_id: str, db) -> Row | None:
        stmt = (
            select(
                Artist.artist_id,
                Artist.name.label("artist_name"),
                Artist.image_url,
                Artist.spotify_url,
                Artist.popularity,
                Artist.genres
            )
            .where(Artist.artist_id == artist_id)
        )

        result = await db.execute(stmt)
        return result.one_or_none()

    @staticmethod
    async def get_streams_by_day_logic(user_id: str, db) -> list:
        stmt = (
            select(
                func.to_char(ListeningHistory.played_at, 'Day').label('day_of_week'),
                func.count(ListeningHistory.track_id).label('stream_count')
            )
            .where(ListeningHistory.user_id == user_id)
            .group_by('day_of_week')
            .order_by('day_of_week')
        )

        result = await db.execute(stmt)
        return result.all()

    @staticmethod
    async def get_streams_by_month_logic(user_id: str, db) -> list:
        stmt = (
            select(
                func.to_char(ListeningHistory.played_at, 'Month').label("month"),
                func.count(ListeningHistory.track_id).label("stream_count"),
                cast(func.to_char(ListeningHistory.played_at, 'MM'), Integer).label("month_num")
            )
            .where(ListeningHistory.user_id == user_id)
            .group_by("month", "month_num")
            .order_by("month_num")
        )

        result = await db.execute(stmt)
        rows = result.all()  # ✅ FIXED HERE
        return [dict(month=row.month.strip(), stream_count=row.stream_count) for row in rows]

    @staticmethod
    async def on_this_day_logic(user_id: str, db) -> tuple[date, list[dict]]:
        today = date.today()

        stmt = select(
            ListeningHistory.track_id,
            Track.name.label("track_name"),
            Track.artist_name,
            Track.album_name,
            Track.album_image_url,
            Track.spotify_url,
            func.date(ListeningHistory.played_at).label("listened_date")
        ).join(Track, ListeningHistory.track_id == Track.track_id
        ).where(
            func.date(ListeningHistory.played_at) == today,
            ListeningHistory.user_id == user_id
        )

        result = await db.execute(stmt)
        rows = result.all()
        return today, [dict(row._mapping) for row in rows]

