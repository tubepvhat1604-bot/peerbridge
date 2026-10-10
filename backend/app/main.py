import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .checkin.router import router as checkin_router
from .config import get_settings
from .db import init_db
from .demo import enabled as demo_enabled
from .demo import router as demo_router
from .demo import seed_demo
from .home.router import router as home_router
from .matching.router import router as data1_matching_router
from .metrics.router import jobs_router
from .metrics.router import router as data1_metrics_router
from .onboarding.router import router as onboarding_router
from .rate_limit import RateLimitMiddleware
from .routers import (
    auth,
    chat,
    coach,
    connections,
    discovery,
    instructor_moderation,
    interactions,
    matches,
    moderation,
    plans,
    profiles,
    sessions,
    study_room,
)
from .services.seed import seed_profiles
from .session_review.router import router as session_review_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_profiles()
    if demo_enabled():
        seed_demo()
    loop_task = None
    minutes = int(os.environ.get("LOOP_INTERVAL_MINUTES", "0") or 0)
    if minutes > 0:  # vòng AI định kỳ: đo tiến độ + coach cho mọi cặp
        from .loop.trigger import periodic

        loop_task = asyncio.create_task(periodic(minutes))
    yield
    if loop_task:
        loop_task.cancel()


app = FastAPI(
    title="Đồng Điệu API",
    version="0.1.0",
    description="Backend demo cho hồ sơ, gợi ý kết nối, match, chat và AI agent.",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.rate_limit_per_minute)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
settings.upload_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_path), name="uploads")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "service": "dong-dieu-backend", "mode": settings.app_env}


@app.get("/api/v1/dashboard", tags=["dashboard"])
def dashboard() -> dict:
    from .db import database

    with database() as connection:
        profiles_count = connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        matches_count = connection.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        messages_count = connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    return {"profiles": profiles_count, "matches": matches_count, "messages": messages_count}


for router in (
    data1_metrics_router,
    data1_matching_router,
    onboarding_router,
    auth.router,
    profiles.router,
    discovery.router,
    interactions.router,
    matches.router,
    connections.router,
    sessions.router,
    moderation.router,
    chat.router,
    plans.router,
    coach.router,
    checkin_router,
    home_router,
    demo_router,
    session_review_router,
):
    app.include_router(router, prefix="/api/v1")

app.include_router(study_room.router)
app.include_router(jobs_router)
app.include_router(instructor_moderation.router)

# Nối các phần qua cổng đã chừa sẵn: Data 1 đo tiến độ từ plan (Data 2) + check-in (Vision); coach đọc số đo đó.
from .loop.ai_clients import get_team_plan_service, get_team_reranker  # noqa: E402
from .loop.coach_bridge import get_team_coach_service  # noqa: E402
from .loop.measurement import get_team_measurement_source  # noqa: E402
from .matching.service import get_reranker  # noqa: E402
from .metrics.adapters import get_measurement_source  # noqa: E402
from .services.coach import get_coach_service  # noqa: E402
from .services.plans import get_plan_service  # noqa: E402

app.dependency_overrides[get_measurement_source] = get_team_measurement_source
app.dependency_overrides[get_coach_service] = get_team_coach_service
app.dependency_overrides[get_reranker] = get_team_reranker
app.dependency_overrides[get_plan_service] = get_team_plan_service

if settings.app_env == "development":
    from .checkin.demo import mount_demo

    mount_demo(app)
