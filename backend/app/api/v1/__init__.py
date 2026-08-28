from fastapi import APIRouter

from app.api.v1 import auth, children, health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(children.router)
api_router.include_router(health.router)
