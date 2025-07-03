from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db_connection
from app.db import Message
from app.schemas.messages import MessageCreate, MessageRead

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("/", response_model=MessageRead)
async def send_message(
    message: MessageCreate,
    request: Request
):
    db = await get_db_connection()

    sender_id = request.session.get("user_id")
    if not sender_id:
        raise HTTPException(status_code=403, detail="Not authenticated")

    new_message = Message(
        sender_id=sender_id,
        receiver_id=message.receiver_id,
        content=message.content,
    )

    db.add(new_message)
    await db.commit()
    await db.refresh(new_message)

    return new_message


@router.get("/inbox", response_model=list[MessageRead])
async def get_inbox(request: Request):
    db = await get_db_connection()
    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(status_code=403, detail="Not authenticated")

    stmt = select(Message).where(Message.receiver_id == user_id).order_by(Message.timestamp.desc())
    result = await db.execute(stmt)
    messages = result.scalars().all()

    return messages
