from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db_connection
from app.db import Message, User
from app.schemas.messages import MessageCreate, MessageRead, UserShort
from sqlalchemy.orm import joinedload

router = APIRouter(prefix="/messages", tags=["messages"])

@router.post("/", response_model=MessageRead)
async def send_message(message: MessageCreate, request: Request):
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
    await db.refresh(new_message, attribute_names=["sender", "receiver"])
    return new_message

@router.get("/inbox", response_model=list[MessageRead])
async def get_inbox(request: Request):
    db = await get_db_connection()
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=403, detail="Not authenticated")

    stmt = select(Message).options(
        joinedload(Message.sender), joinedload(Message.receiver)
    ).where(
        Message.receiver_id == user_id
    ).order_by(Message.timestamp.desc())

    result = await db.execute(stmt)
    messages = result.scalars().all()
    return messages

@router.get("/recent-users", response_model=list[UserShort])
async def get_recent_users(request: Request):
    db = await get_db_connection()
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=403, detail="Not authenticated")

    stmt = select(User).join(Message, ((Message.sender_id == User.user_id) | (Message.receiver_id == User.user_id))).where(
        (Message.sender_id == user_id) | (Message.receiver_id == user_id),
        User.user_id != user_id
    ).distinct(User.user_id)

    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/search-users", response_model=list[UserShort])
async def search_users(q: str, request: Request):
    db = await get_db_connection()
    stmt = select(User).where(User.username.ilike(f"%{q}%"))
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/thread/{other_user_id}", response_model=list[MessageRead])
async def get_conversation(other_user_id: str, request: Request):
    db = await get_db_connection()
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=403, detail="Not authenticated")

    stmt = select(Message).options(
        joinedload(Message.sender),
        joinedload(Message.receiver)
    ).where(
        ((Message.sender_id == user_id) & (Message.receiver_id == other_user_id)) |
        ((Message.sender_id == other_user_id) & (Message.receiver_id == user_id))
    ).order_by(Message.timestamp.asc())

    result = await db.execute(stmt)
    messages = result.scalars().all()
    return messages
