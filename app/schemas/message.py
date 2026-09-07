from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from typing import Optional, Literal

class MessageBase(BaseModel):
    content: str
    role: Literal["user", "assistant"]
    user_id: UUID
    conversation_id: UUID

class MessageCreate(MessageBase):
    pass

class MessageUpdate(MessageBase):
    content: Optional[str] = None

class MessageResponse(MessageBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime