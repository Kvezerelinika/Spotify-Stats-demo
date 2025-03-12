from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse  
import time

from app.database import get_db_connection
from app.helpers import (get_user_info, get_top_artists_db, get_top_tracks_db, get_track_play_counts, get_daily_play_counts, get_total_play_count, get_total_play_today, get_current_playing, get_total_listening_time, get_daily_listening_time, get_top_genres, update_user_music_data)
from app.oauth import user_info_to_database
from app.spotify_api import get_spotify_user_profile

@app.get("/dashboard")
async def dashboard(request: Request):
    with get_db_connection() as db:
        with db.cursor() as cursor:
            try:
                # Fetch user session
                token = request.session.get("spotify_token")
                user_id = request.session.get("user_id")
                
                if not token or not user_id:
                    return RedirectResponse(url="/login")  # Redirect if session is invalid

                # Cache control: Only fetch new data if cache has expired
                last_fetched = request.session.get("last_fetched", 0)
                cache_expiry = 3600  # 1 hour

                if time.time() - last_fetched > cache_expiry:
                    print("Fetching fresh data from Spotify...")

                    # Fetch and update user profile
                    user_profile = get_spotify_user_profile(token)
                    user_data = user_info_to_database(user_profile)
                    user_id = user_data[0][0]  # Ensure correct user_id
                    request.session["user_id"] = user_id  # Store in session

                    # Fetch and update user’s music data
                    await update_user_music_data(token, user_id)

                    request.session["last_fetched"] = time.time()  # Update only after data is successfully fetched

                # Fetch user details
                user_info = get_user_info(user_id, cursor)
                if user_info:
                    user_image, user_name = user_info
                else:
                    user_image, user_name = None, "Unknown User"

                # Fetch dashboard stats
                top_artist_list = get_top_artists_db(user_id, cursor)
                top_tracks_list = get_top_tracks_db(user_id, cursor)
                track_play_counts = get_track_play_counts(user_id, cursor)
                daily_play_count = get_daily_play_counts(user_id, cursor)
                total_play_count = get_total_play_count(user_id, cursor)
                total_play_today = get_total_play_today(user_id, cursor)
                playing_now_data = get_current_playing(user_id, cursor)
                total_listened_minutes, total_listened_hours = get_total_listening_time(user_id, cursor)
                daily_listening_time = get_daily_listening_time(user_id, cursor)
                top_genres = get_top_genres(user_id, top_artist_list)

            except Exception as e:
                print(f"Error during fetching data: {e}")
                return {"error": "There was an issue fetching data. Please try again later."}

            finally:
                # Close database connection
                cursor.close()
                db.close()

            # Render template
            context = {
                "request": request,
                "user_id": user_id,
                "track_play_counts": track_play_counts,
                "daily_play_counts": daily_play_count,
                "total_play_count": total_play_count,
                "total_play_today": total_play_today,
                "top_artist_list": top_artist_list,
                "top_genres": top_genres,
                "top_tracks_list": top_tracks_list,
                "total_listened_minutes": total_listened_minutes,
                "total_listened_hours": total_listened_hours,
                "daily_listening_time": daily_listening_time,
                "user_image": user_image,
                "user_name": user_name,
                "track_name": playing_now_data.get("track_name"),
                "artist_name": playing_now_data.get("artist_name"),
                "album_img": playing_now_data.get("album_image_url"),
            }

            return templates.TemplateResponse("dashboard.html", context)