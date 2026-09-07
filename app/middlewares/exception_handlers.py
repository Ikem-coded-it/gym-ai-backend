from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logger import logger


async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except StarletteHTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)},
        )
