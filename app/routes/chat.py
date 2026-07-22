import os
from fastapi import APIRouter, Body, HTTPException, Request, Response, status, UploadFile, File, Form
from pydantic import BaseModel, Field
from app.logger import logger
from dotenv import load_dotenv
from app.services.rag.llm import get_llm_chain
from app.services.rag.retriever import create_retriever
from fastapi.responses import JSONResponse
from app.services.rag.query_handlers import query_chain
from typing import List, Dict, Any, Optional
from app.logger import logger

load_dotenv(override=True)
router = APIRouter()

@router.post("/chat")
async def chat(question: str = Form(...)):
    try:
        logger.info(f"User question: {question}")
        
        retriever = create_retriever()
        chain = get_llm_chain(retriever)
        response = query_chain(chain, question)
        
        logger.info("Query chain completed successfully")
        return JSONResponse(content={"response": response})
    except Exception as e:
        logger.exception(f"Error answering question: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))