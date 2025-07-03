from pydantic import BaseModel
from datetime import datetime

class MessageCreate(BaseModel):
    receiver_id: str
    content: str

class MessageRead(BaseModel):
    id: int
    sender_id: str
    receiver_id: str
    content: str
    timestamp: datetime
    is_read: bool

    class Config:
        from_attributes = True  # Use instead of orm_mode in Pydantic v2
