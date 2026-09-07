from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conversation import conversation_service


def messages_to_langchain(messages) -> list[BaseMessage]:
    return [
        HumanMessage(content=message.content)
        if message.role == "user"
        else AIMessage(content=message.content)
        for message in messages
    ]


async def load_chat_history(
    db: AsyncSession,
    conversation_id: str,
) -> list[BaseMessage]:
    history = await conversation_service.get_conversation_history(
        db,
        conversation_id,
    )
    return messages_to_langchain(history)
