import os
from typing import Annotated
from fastapi import APIRouter, HTTPException, status, Form
from app.logger import logger
from dotenv import load_dotenv
from app.services.rag.llm import get_llm_chain
from app.services.rag.retriever import create_retriever
from fastapi.responses import JSONResponse
from app.services.rag.query_handlers import query_chain
from app.logger import logger
from app.schemas.chat import ChatCreate, ChatResponse

load_dotenv(override=True)
router = APIRouter()

@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Chat with the bot",
    description="Chat with the bot and get a response",
)
async def chat(chat: ChatCreate):
    try:
        logger.info(f"User question: {chat.message}")
        
        retriever = create_retriever()
        chain = get_llm_chain(retriever)
        response = query_chain(chain, chat.message)
        
        logger.info("Query chain completed successfully")
        return ChatResponse(message=response)
    except Exception as e:
        logger.exception(f"Error answering question: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))