from fastapi import APIRouter

from app.api.v1 import (
    admin_data,
    admin_jobs,
    admin_settings,
    auth,
    checkin,
    children,
    chores,
    disputes,
    health,
    occurrences,
    payouts,
    penalties,
    push,
    submissions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(children.router)
api_router.include_router(chores.router)
api_router.include_router(occurrences.router)
api_router.include_router(disputes.router)
api_router.include_router(submissions.router)
api_router.include_router(payouts.router)
api_router.include_router(penalties.router)
api_router.include_router(checkin.router)
api_router.include_router(push.router)
api_router.include_router(admin_data.router)
api_router.include_router(admin_jobs.router)
api_router.include_router(admin_settings.router)
api_router.include_router(health.router)
