import json
from typing import Annotated

from auth import CurrentUser
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session, get_db
from app.logger import logger
from app.schemas.chat import ChatCreate, ChatHistoryResponse
from app.schemas.message import MessageResponse
from app.services.conversation import conversation_service
from app.services.rag.memory import load_chat_history
from app.services.rag.query_handlers import stream_agent
from app.services.rag.retriever import create_retriever

load_dotenv(override=True)
router = APIRouter()

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get(
    "/history",
    response_model=ChatHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get chat message history",
    description="Get the current user's chat message history for the AI coach screen",
)
async def get_chat_history(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        conversation, messages = await conversation_service.get_user_chat_history(
            db,
            user_id=str(current_user.id),
        )
        return ChatHistoryResponse(
            conversation_id=conversation.id,
            messages=[
                MessageResponse.model_validate(message)
                for message in messages
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching chat history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    summary="Chat with the bot",
    description="Stream a chat response as server-sent events",
)
async def chat(
    chat: ChatCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info(f"User question: {chat.message}")

    try:
        conversation = await conversation_service.get_or_create_conversation(
            db,
            user_id=str(current_user.id),
        )
        conversation_id = str(conversation.id)
        user_id = str(current_user.id)

        logger.info(f"Conversation: {conversation_id}")

        retriever = create_retriever()

        history = await load_chat_history(db, conversation_id)

        await conversation_service.save_message(
            db,
            conversation_id,
            user_id,
            "user",
            chat.message,
        )
        await db.commit()
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Error preparing chat stream: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    async def event_stream():
        response_parts: list[str] = []

        yield _sse({"type": "start", "conversation_id": conversation_id})

        try:
            async for token in stream_agent(
                db, user_id, chat.message, history, retriever
            ):
                response_parts.append(token)
                yield _sse({"type": "token", "content": token})

            full_response = "".join(response_parts)

            async with async_session() as session:
                assistant_message = await conversation_service.save_message(
                    session,
                    conversation_id,
                    user_id,
                    "assistant",
                    full_response,
                )
                await session.commit()

            yield _sse({
                "type": "done",
                "message_id": str(assistant_message.id),
            })
            logger.info("Chat stream completed and assistant message saved")
        except Exception as e:
            logger.exception(f"Error streaming chat: {e}")
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
