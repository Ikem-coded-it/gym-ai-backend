from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.logger import logger

async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(f"Exception occurred: {e}")
        return JSONResponse(status_code=500, content={"message": "Internal Server Error"})