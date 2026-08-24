from datetime import timedelta
from typing import Annotated
from dotenv import load_dotenv

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm

from app.logger import logger
from app.schemas.user import UserCreate, UserPublic, UserPrivate, Token
from app.models.user import User as user_model
from app.db import get_db

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.logger import logger

from auth import (
    hash_password,
    verify_password,
    create_access_token,
    CurrentUser
)

from config import settings

load_dotenv(override=True)
router = APIRouter()

@router.post(
    "/signup",
    response_model=UserPrivate,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
    description="Create a new user with the given information",
)
async def signup(user: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    logger.info(f"New user signup started: {user}")
    result = await db.execute(
        select(user_model).where(
            func.lower(user_model.username) == user.username.lower()
        ),
    )
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    result = await db.execute(
        select(user_model).where(
            func.lower(user_model.email) == user.email.lower()
        ),
    )
    existing_email = result.scalars().first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    new_user = user_model(
        username=user.username,
        email=user.email.lower(),
        first_name=user.first_name,
        last_name=user.last_name,
        password_hash=hash_password(user.password),
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    logger.info(f"New user signup finished: {new_user}")
    return new_user

@router.post("/login", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Look up user by email (case-insensitive)
    # Note: OAuth2PasswordRequestForm uses "username" field, but we treat it as email
    result = await db.execute(
        select(user_model).where(
            func.lower(user_model.email) == form_data.username.lower(),
        ),
    )
    user = result.scalars().first()

    # Verify user exists and password is correct
    # Don't reveal which one failed (security best practice)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token with user id as subject
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")

@router.get("/me", response_model=UserPrivate)
async def get_current_user(current_user: CurrentUser):
    """Get the currently authenticated user."""
    return current_user