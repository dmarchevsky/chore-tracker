from fastapi import APIRouter

from app.api.v1 import (
    auth,
    checkin,
    children,
    chores,
    health,
    occurrences,
    payouts,
    submissions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(children.router)
api_router.include_router(chores.router)
api_router.include_router(occurrences.router)
api_router.include_router(submissions.router)
api_router.include_router(payouts.router)
api_router.include_router(checkin.router)
api_router.include_router(health.router)
