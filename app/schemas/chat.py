# app/schemas/chat.py
from pydantic import BaseModel, Field
from uuid import UUID

from app.schemas.message import MessageResponse


class ChatBase(BaseModel):
    message: str = Field(min_length=1)

class ChatCreate(ChatBase):
    pass

class ChatResponse(BaseModel):
    message: str
    sources: list[str] = []

class ChatHistoryResponse(BaseModel):
    conversation_id: UUID
    messages: list[MessageResponse] = []
