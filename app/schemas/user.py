# app/schemas/user.py
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from datetime import datetime
from uuid import UUID
from typing import Optional

class UserBase(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    email: EmailStr = Field(unique=True, max_length=120)
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=200)
    pass

class UserUpdate(BaseModel):
    username: Optional[str] = Field(min_length=3, max_length=20)
    email: Optional[EmailStr] = Field(unique=True, max_length=120)
    first_name: Optional[str] = Field(min_length=1, max_length=50)
    last_name: Optional[str] = Field(min_length=1, max_length=50)
    
class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    username: str = Field(min_length=3, max_length=20)
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    created_at: datetime
    updated_at: datetime
    
class UserPrivate(UserPublic):
    email: EmailStr = Field(unique=True, max_length=120)
    password_hash: str = Field(min_length=8, max_length=200)
    
class Token(BaseModel):
    access_token: str = Field(min_length=1, max_length=200)
    token_type: str = Field(min_length=1, max_length=20)