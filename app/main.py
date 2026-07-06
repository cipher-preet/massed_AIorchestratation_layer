from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chat_routes import router as chat_router
from app.api.routes.health_routes import router as health_router
from app.config.settings import settings
from app.core.logger import configure_logging
from app.mcp_client.node_mcp_client import node_mcp_client


configure_logging()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1/ai")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await node_mcp_client.close()
