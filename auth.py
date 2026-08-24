from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi.security import OAuth2PasswordBearer
from fastapi import HTTPException, status, Depends
from pwdlib import PasswordHash

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from app.db import get_db
from app.models.user import User as user_model

password_hash = PasswordHash.recommended() # Use argon2 default recommended settings, best for security

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login") #Has to match our login endpoint path, OAuth2PasswordBearer automatically retrieves the token from the authorization header


def hash_password(password: str) -> str: # Hash the password using default salt from argon2
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)
#argon2 generates a random salt for each hash, so the same password produces a different hash each time
# That means attackers can't precompute a list of common password hashes and look yours up, each one is unique


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.access_token_expire_minutes,
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )
    return encoded_jwt


def verify_access_token(token: str) -> str | None:
    """Verify a JWT access token and return the subject (user id) if valid."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError:
        return None
    else:
        return payload.get("sub")
    
async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> user_model:
    user_id = verify_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(user_model).where(user_model.id == user_id),
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[user_model, Depends(get_current_user)]