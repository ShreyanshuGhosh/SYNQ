from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import conversations, files, webhooks
from app.routers.conversations import models_router

app = FastAPI(
    title="SYNQ API",
    description="Cross-agent conversation continuity backend",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations.router)
app.include_router(models_router)
app.include_router(webhooks.router)
app.include_router(files.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
