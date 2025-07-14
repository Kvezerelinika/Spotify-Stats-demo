from sqlalchemy import create_engine, Column, Integer, String, TIMESTAMP, ForeignKey, Boolean, Date, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.orm import relationship
from sqlalchemy.types import ARRAY
from sqlalchemy.sql import func

DATABASE_URL = "postgresql://postgres:Manowar28%40%40@localhost/postgres"

engine = create_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class ListeningHistory(Base):
    __tablename__ = "listening_history"

    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, primary_key=True)  # Foreign key to User
    track_id = Column(String, ForeignKey("tracks.track_id"), nullable=False, primary_key=True)  # Foreign key to Track
    played_at = Column(TIMESTAMP, nullable=False, primary_key=True)  # Timestamp of when the track was played

    # Relationship with Users and Tracks
    users = relationship("User", back_populates="listening_history")
    tracks = relationship("Track", back_populates="listening_history")


class User(Base):
    __tablename__ = "users"
    
    user_id = Column(String, primary_key=True)  # user_id is the primary key
    display_name = Column(String, nullable=True)
    profile_url = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    last_updated = Column(TIMESTAMP, default=func.now())  # Default value 'now()' for timestamp
    username = Column(String, nullable=False)  # assuming it's required (change if not)
    email = Column(String, nullable=False)     # assuming it's required (change if not)
    country = Column(String, nullable=True)
    product = Column(String, nullable=True)
    followers = Column(String, nullable=True)
    external_urls = Column(String, nullable=True)
    href = Column(String, nullable=True)
    uri = Column(String, nullable=True)
    type = Column(String, nullable=True)
    access_token = Column(String, nullable=True)  # Access token for Spotify API
    refresh_token = Column(String, nullable=True)  # Refresh token for Spotify API
    token_expires = Column(DateTime(timezone=True))  # Expiration time for the access token
    custom_username = Column(String, unique=True, nullable=True)
    bio = Column(Text)
    preferred_language = Column(String)
    timezone = Column(String)


    # Add relationships if necessary (e.g., with listening_history, top_artists, etc.)
    listening_history = relationship("ListeningHistory", back_populates="users")
    users_top_artists = relationship("UsersTopArtists", back_populates="users")
    users_top_tracks = relationship("UsersTopTracks", back_populates="users")
    followed_artists = relationship("UserFollowedArtist", back_populates="user")
    payment_methods = relationship("PaymentMethod", back_populates="user")
    sent_messages = relationship("Message", back_populates="sender", foreign_keys='Message.sender_id', cascade="all, delete-orphan")
    received_messages = relationship("Message", back_populates="receiver", foreign_keys='Message.receiver_id', cascade="all, delete-orphan")
    followings = relationship("UserConnection", foreign_keys="[UserConnection.user_id]", back_populates="user", cascade="all, delete-orphan")
    followers = relationship("UserConnection", foreign_keys="[UserConnection.friend_id]", back_populates="friend", cascade="all, delete-orphan")


class Track(Base):
    __tablename__ = "tracks"
    
    track_id = Column(String, primary_key=True)  # track_id is the primary key
    name = Column(String, nullable=False)  # Track name (cannot be null)
    album_id = Column(String, ForeignKey("albums.album_id"), nullable=True)  # Foreign key to album
    artist_id = Column(String, ForeignKey("artists.artist_id"), nullable=True)  # ✅ add this
    artist_name = Column(String, nullable=True)  # ✅ add this
    spotify_url = Column(String, nullable=True)  # URL to the track on Spotify
    duration_ms = Column(Integer, nullable=True)  # Duration of the track in milliseconds
    popularity = Column(Integer, nullable=True)  # Popularity score of the track
    explicit = Column(Boolean, nullable=True)  # Whether the track is explicit
    track_number = Column(Integer, nullable=True)  # Track number on the album
    album_release_date = Column(Date, nullable=True)  # Album release date
    album_image_url = Column(String(255), nullable=True)  # URL of the album image
    album_name = Column(String(255), nullable=True)  # Name of the album
    


    # Relationships
    albums = relationship("Album", back_populates="tracks")  # Relationship with Album
    listening_history = relationship("ListeningHistory", back_populates="tracks")  # Relationship with ListeningHistory
    users_top_tracks = relationship("UsersTopTracks", back_populates="tracks")  # Relationship with UsersTopTracks
    track_artists = relationship("TrackArtist", back_populates="tracks")  # Relationship with TrackArtist (many-to-many with Artist)
    primary_artist = relationship("Artist", foreign_keys=[artist_id]) # Relationship with primary artist (if needed, otherwise can be removed)
    global_stats = relationship("GlobalTrackStats", back_populates="track", uselist=False)




class Artist(Base):
    __tablename__ = "artists"

    artist_id = Column(String, primary_key=True, index=True)  # Changed to String to match the schema
    name = Column(String, nullable=False)  # Artist name (cannot be null)
    genres = Column(ARRAY(String))  # Use ARRAY for list of strings (genres is an array of text)
    image_url = Column(String)  # URL to the artist's image
    spotify_url = Column(String)  # URL to the artist on Spotify
    followers = Column(Integer)  # Number of followers
    popularity = Column(Integer, default=0)  # Popularity score of the artist
    uri = Column(String(255))  # Spotify URI for the artist


    albums = relationship("Album", back_populates="artists")     # Relationship with Albums
    track_artists = relationship("TrackArtist", back_populates="artists")     # Relationship with track_artists (many-to-many with Track)
    users_top_artists = relationship("UsersTopArtists", back_populates="artists")     # Relationship with users_top_artists (many-to-many with User)
    tracks = relationship("Track", back_populates="primary_artist", foreign_keys="[Track.artist_id]") # Relationship with Tracks (if needed, otherwise can be removed)
    global_stats = relationship("GlobalArtistStats", back_populates="artist", uselist=False)
    followers = relationship("UserFollowedArtist", back_populates="artist")



class Album(Base):
    __tablename__ = "albums"

    album_id = Column(String, nullable=False, primary_key=True)  # album_id is the primary key
    name = Column(String, nullable=False)  # Album name (cannot be null)
    artist_id = Column(String, ForeignKey("artists.artist_id")) # Foreign key to artist
    image_url = Column(String)  # URL to the album's image
    spotify_url = Column(String)  # URL to the album on Spotify
    release_date = Column(Date)  # Release date of the album
    popularity = Column(Integer)  # Popularity score of the album
    label = Column(String(255))  # Label of the album (optional, max length 255 characters)
    total_tracks = Column(Integer, nullable=True)  # Total number of tracks in the album (optional)

    tracks = relationship("Track", back_populates="albums")  # Relationship with Tracks
    artists = relationship("Artist", back_populates="albums") # Relationship with Artist (optional, since artist_id can be NULL)



class UsersTopArtists(Base):
    __tablename__ = "users_top_artists"

    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, primary_key=True)  # Foreign key to User
    artist_id = Column(String, ForeignKey("artists.artist_id"), nullable=False, primary_key=True)  # Foreign key to Artist
    rank = Column(Integer, nullable=False)  # Rank of the artist in the user's top artists
    time_range = Column(String, nullable=False)  # Time range for the top artists (e.g., "short_term", "medium_term", "long_term")
    last_updated = Column(TIMESTAMP, default=func.now())  # Default value 'now()' for timestamp (correct usage)

    # Relationships to User and Artist (if needed)
    users = relationship("User", back_populates="users_top_artists")
    artists = relationship("Artist", back_populates="users_top_artists")


class UsersTopTracks(Base):
    __tablename__ = "users_top_tracks"

    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, primary_key=True)  # Foreign key to User
    track_id = Column(String, ForeignKey("tracks.track_id"), nullable=False, primary_key=True)  # Foreign key to Track
    rank = Column(Integer, nullable=False)  # Rank of the track in the user's top tracks
    time_range = Column(String, nullable=False)  # Time range for the top tracks (e.g., "short_term", "medium_term", "long_term")
    last_updated = Column(TIMESTAMP, default=func.now())  # Default value 'now()' for timestamp (correct usage)

    users = relationship("User", back_populates="users_top_tracks")
    tracks = relationship("Track", back_populates="users_top_tracks")  # Relationship to Track (if needed)



class TrackArtist(Base):
    __tablename__ = 'track_artists'
    
    track_id = Column(String, ForeignKey('tracks.track_id'), primary_key=True)
    artist_id = Column(String, ForeignKey('artists.artist_id'), primary_key=True)
    artist_name = Column(String)
    
    tracks = relationship('Track', back_populates='track_artists')
    artists = relationship('Artist', back_populates='track_artists')


class UserConnection(Base):
    __tablename__ = "user_connections"
    user_id = Column(String, ForeignKey("users.user_id"), primary_key=True)
    friend_id = Column(String, ForeignKey("users.user_id"), primary_key=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    user = relationship("User", foreign_keys=[user_id], back_populates="followings")
    friend = relationship("User", foreign_keys=[friend_id], back_populates="followers")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    receiver_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), server_default=func.now())
    is_read = Column(Boolean, default=False)

    sender = relationship("User", back_populates="sent_messages", foreign_keys=[sender_id])
    receiver = relationship("User", back_populates="received_messages", foreign_keys=[receiver_id])



class GlobalArtistStats(Base):
    __tablename__ = "global_artist_stats"
    artist_id = Column(String, ForeignKey("artists.artist_id"), primary_key=True)
    total_plays = Column(Integer, default=0)
    unique_users = Column(Integer, default=0)

    artist = relationship("Artist", back_populates="global_stats")


class GlobalTrackStats(Base):
    __tablename__ = "global_track_stats"
    track_id = Column(String, ForeignKey("tracks.track_id"), primary_key=True)
    total_plays = Column(Integer, default=0)
    unique_users = Column(Integer, default=0)

    track = relationship("Track", back_populates="global_stats")


class UserFollowedArtist(Base):
    __tablename__ = "user_followed_artists"
    user_id = Column(String, ForeignKey("users.user_id"), primary_key=True)
    artist_id = Column(String, ForeignKey("artists.artist_id"), primary_key=True)
    followed_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="followed_artists")
    artist = relationship("Artist", back_populates="followers")


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    card_last4 = Column(String(4), nullable=False)
    card_brand = Column(String(50))
    expiration_date = Column(String(10))  # e.g., MM/YY
    is_active = Column(Boolean, default=True)
    added_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="payment_methods")
