# app/schemas/user.py
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from datetime import datetime
from uuid import UUID
from typing import Optional

class ChatBase(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    
class ChatCreate(ChatBase):
    pass
    
class ChatResponse(ChatBase):
    model_config = ConfigDict(from_attributes=True) # so pydantic can read from SQLAlchemy model
    id: UUID
    created_at: datetime
    updated_at: datetime