from app.logger import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.message import Message
from app.models.conversation import Conversation
from app.schemas.conversation import ConversationResponse
import uuid


class ConversationService:
    @staticmethod
    async def save_message(
        db: AsyncSession,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> Message:
        message = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            content=content,
        )
        db.add(message)
        await db.flush()
        return message

    @staticmethod
    async def get_conversation_history(
        db: AsyncSession,
        conversation_id: str,
        limit: int = 50,
    ) -> list[Message]:
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        history = list(reversed(result.scalars().all()))
        logger.info(f"Conversation history count: {len(history)}")
        return history

    @staticmethod
    async def get_user_chat_history(
        db: AsyncSession,
        user_id: str,
        limit: int = 50,
    ) -> tuple[ConversationResponse, list[Message]]:
        conversation = await ConversationService.get_or_create_conversation(
            db,
            user_id,
        )
        messages = await ConversationService.get_conversation_history(
            db,
            str(conversation.id),
            limit=limit,
        )
        return conversation, messages

    @staticmethod
    async def get_or_create_conversation(
        db: AsyncSession,
        user_id: str,
    ) -> ConversationResponse:
        result = await db.execute(
            select(Conversation).where(Conversation.user_id == user_id)
        )
        conversation = result.scalar_one_or_none()
        if conversation:
            return ConversationResponse.model_validate(conversation)

        conversation = Conversation(
            id=str(uuid.uuid4()),
            user_id=user_id,
        )
        db.add(conversation)
        await db.flush()
        await db.commit()
        await db.refresh(conversation)
        return ConversationResponse.model_validate(conversation)


conversation_service = ConversationService()
