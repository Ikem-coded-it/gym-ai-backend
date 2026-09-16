import re

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from app.logger import logger
from app.services.rag.llm import MODEL, OPENAI_API_KEY

SAVE_CONFIRMATION_PATTERN = re.compile(
    r"^\s*(confirm(?:ed)?|yes(?:\s+save)?|save(?:\s+it)?|looks good|go ahead|do it)\s*\.?\s*$",
    re.IGNORECASE,
)


def message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return " ".join(parts)
    return str(content or "")


def is_explicit_save_confirmation(question: str) -> bool:
    return bool(SAVE_CONFIRMATION_PATTERN.match(question.strip()))

def history_has_pending_workout_review(history: list | None) -> bool:
    # TODO: This is a temporary solution to check if the chat history has a pending workout review
    # We should use a more professional and scalable approach to check if the chat history has a pending workout review
    # Maybe use redis to store the pending workout review and check if it exists
    if not history:
        return False

    for message in reversed(history):
        if not isinstance(message, AIMessage):
            continue
        text = message_text(message).lower()
        if "confirm" not in text:
            continue
        if "•" in text or "×" in text or " x " in text or "@" in text:
            return True
    return False


# This function is used to check if the user has a pending workout review
#  by checking if the user has explicitly confirmed the save and if the chat history has a pending workout review
def awaiting_workout_save(question: str, history: list | None) -> bool:
    return is_explicit_save_confirmation(question) and history_has_pending_workout_review(
        history
    )


def get_llm(*, streaming: bool) -> ChatOpenAI:
    return ChatOpenAI(
        model=MODEL,
        temperature=0,
        api_key=OPENAI_API_KEY,
        streaming=streaming,
    )


async def execute_tool_call(
    tool_map: dict[str, BaseTool],
    tool_call,
) -> str:
    tool_name = tool_call["name"] if isinstance(tool_call, dict) else tool_call.name
    tool_args = tool_call["args"] if isinstance(tool_call, dict) else tool_call.args
    tool = tool_map.get(tool_name)
    if tool is None:
        return f"Error: unknown tool '{tool_name}'"

    try:
        result = await tool.ainvoke(tool_args)
        return str(result)
    except Exception as e:
        logger.exception(f"Tool '{tool_name}' failed: {e}")
        return f"Error running {tool_name}: {e}"
