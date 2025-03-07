import psycopg2
from datetime import datetime
import requests
from fastapi import Request
import os

from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")


def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname = DB_NAME,
            user = DB_USER,
            password = DB_PASSWORD,
            host = DB_HOST,
            port = DB_PORT
        )
        print("The conenction has been estabilished!")
        return conn
    except Exception as e:
        print(f"Connection error: {e}")

def fetch_current_image_urls(user_id):
    """Fetch current image URLs from the database for the given user."""
    db = get_db_connection()
    cursor = db.cursor()
    print("started 1")

    cursor.execute("""
        SELECT track_id, album_image_url FROM listening_history
        WHERE user_id = %s
    """, (user_id,))

    records = cursor.fetchall()
    cursor.close()
    db.close()
    
    return records

def fetch_latest_album_images(token, track_id):
    """Fetch the latest album image URL from the API using the track ID."""
    api_url = f"https://api.spotify.com/v1/tracks/{track_id}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Send the GET request to the API
        response = requests.get(api_url, headers=headers)
        
        # Check if the response is successful (HTTP Status 200)
        if response.status_code == 200:
            api_data = response.json()  # Parse the JSON response
            
            # Extract the album image URL from the response
            album_images = api_data.get("album", {}).get("images", [])
            print("ALBUM IMAGES: ", album_images)
            if album_images:
                return album_images[0]["url"]  # Return the first image URL
            else:
                print("No album images found.")
                return None

        else:
            print(f"Failed to fetch data: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return None


def update_image_urls(user_id, token):
    """Update album image URLs for a user if they have changed."""
    print("started 3")
    # Fetch current image URLs from the database
    current_images = fetch_current_image_urls(user_id)
    
    # List to store records that need to be updated
    updated_records = []
    
    for track_id, current_image_url in current_images:
        # Fetch the latest album image URL from the API
        latest_image_url = fetch_latest_album_images(token, track_id)  # Pass the token here
        
        # If the URL is different, prepare for update
        if latest_image_url and latest_image_url != current_image_url:
            updated_records.append((user_id, track_id, latest_image_url))
    
    if updated_records:
        # Perform the update if there are changes
        db = get_db_connection()
        cursor = db.cursor()

        try:
            cursor.executemany(
                """
                UPDATE listening_history
                SET album_image_url = %s
                WHERE user_id = %s AND track_id = %s
                """,
                [(image_url, user_id, track_id) for user_id, track_id, image_url in updated_records]
            )
            db.commit()
            print(f"Successfully updated {len(updated_records)} album image URLs.")
        
        except psycopg2.Error as e:
            print(f"Database error: {e}")
            db.rollback()
        
        finally:
            cursor.close()
            db.close()
    else:
        print("No changes to album image URLs.")

# Call this method to update image URLs for a specific user
# You need to provide the `request` object along with the `user_id`
user_token = "BQDJJ79Z3EC-83LhMnY6wWSQIWv5DVSWbMw0hz4wGt8OMPdG9l8auDtq9Jyfz_ft3SA9PaFI6nrQT-5J5I-vm4GvKk2vTCInZ80caDL4HCXr6qSXikQUzcIwgb9qhug5PLcI93U7LLjSQiGDHoLrYC9wyD22aCsLCUaZboHFn74bcFN3wwtLKbtFSW9kL74-q_wxHmAC_gwdT2dlSGOJDYtkMlHJukl390gxP7qP21z1rWof"
update_image_urls(user_id="bxbnsyr2xozh2w6motxczqptv", token=user_token)