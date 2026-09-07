from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime
from uuid import UUID
from app.schemas.message import MessageResponse


class ConversationBase(BaseModel):
    user_id: UUID


class ConversationCreate(ConversationBase):
    pass


class ConversationUpdate(BaseModel):
    user_id: Optional[UUID] = None


class ConversationResponse(ConversationBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime


class ConversationWithMessagesResponse(ConversationResponse):
    messages: List[MessageResponse] = []
