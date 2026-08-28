from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middlewares.exception_handlers import catch_exceptions_middleware
from app.router import chat, auth, user, workout, onboarding
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.db import engine, get_db

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Shutdown
    await engine.dispose()
    
app = FastAPI(title="Gym AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware exception handlers
app.middleware("http")(catch_exceptions_middleware)

@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(user.router, prefix="/api/user", tags=["user"])
app.include_router(workout.router, prefix="/api/workout", tags=["workout"])
app.include_router(onboarding.router, prefix="/api/onboarding", tags=["onboarding"])