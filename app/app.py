from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middlewares.exception_handlers import catch_exceptions_middleware
from app.routes.chat import router as chat_router

app = FastAPI(title="Gym AI API")

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

app.include_router(chat_router)