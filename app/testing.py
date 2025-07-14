# testing.py
import asyncio
from app.logic import LogicHandlers
from app.database import get_db_connection


async def test_user_profile(user_id: str):
    async with await get_db_connection() as db:
        user = await LogicHandlers.get_user_profile_logic(user_id, db)
        print("USER PROFILE:", dict(user._mapping) if user else "User not found")


async def test_track(track_id: str):
    async with await get_db_connection() as db:
        track = await LogicHandlers.get_track_details_logic(track_id, db)
        print("TRACK DETAILS:", dict(track._mapping) if track else "Track not found")


async def test_artist(artist_id: str):
    async with await get_db_connection() as db:
        artist = await LogicHandlers.get_artist_details_logic(artist_id, db)
        print("ARTIST DETAILS:", dict(artist._mapping) if artist else "Artist not found")


async def test_album(album_id: str):
    async with await get_db_connection() as db:
        album = await LogicHandlers.get_album_details_logic(album_id, db)
        print("ALBUM DETAILS:", dict(album._mapping) if album else "Album not found")


async def test_streams_by_day(user_id: str):
    async with await get_db_connection() as db:
        result = await LogicHandlers.get_streams_by_day_logic(user_id, db)
        print("STREAMS BY DAY:", result)


async def test_streams_by_month(user_id: str):
    async with await get_db_connection() as db:
        result = await LogicHandlers.get_streams_by_month_logic(user_id, db)
        print("STREAMS BY MONTH:", result)


async def test_on_this_day(user_id: str):
    async with await get_db_connection() as db:
        date_, tracks = await LogicHandlers.on_this_day_logic(user_id, db)
        print(f"On {date_}, YOU LISTENED TO:")

        if isinstance(tracks, str):
            print(tracks)
        else:
            for track in tracks:
                print("-", track["track_name"], "by", track["artist_name"])




user_id = "bxbnsyr2xozh2w6motxczqptv"
track_id = "3LQNvNYMp5sFUzJbIIDspG"
artist_id = "66CXWjxzNUsdJxJ2JdwvnR"
album_id = "2rjfRdmVDBMFT5mamSsVeU"

async def main():
    await test_user_profile(user_id)
    await test_track(track_id)
    await test_artist(artist_id)
    await test_album(album_id)
    await test_streams_by_day(user_id)
    await test_streams_by_month(user_id)
    await test_on_this_day(user_id)

if __name__ == "__main__":
    asyncio.run(main())
