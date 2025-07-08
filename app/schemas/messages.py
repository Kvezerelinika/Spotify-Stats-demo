from pydantic import BaseModel
from datetime import datetime

class UserShort(BaseModel):
    user_id: str
    username: str
    image_url: str | None = None

    class Config:
        from_attributes = True

class MessageCreate(BaseModel):
    receiver_id: str
    content: str

class MessageRead(BaseModel):
    id: int
    sender: UserShort
    receiver: UserShort
    content: str
    timestamp: datetime
    is_read: bool

    class Config:
        from_attributes = True