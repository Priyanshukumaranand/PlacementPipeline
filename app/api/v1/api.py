from fastapi import APIRouter
from app.api.v1.endpoints import debug, gmail_events, gmail_watch, drives

api_router = APIRouter(prefix="/api/v1")

# Include all endpoint routers
api_router.include_router(debug.router)
api_router.include_router(gmail_events.router)
api_router.include_router(gmail_watch.router)
api_router.include_router(drives.router)
