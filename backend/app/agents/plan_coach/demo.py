"""Run the EXISTING app against a new isolated DB, with explicitly simulated time/adapters."""

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4


def serve(port, coach_v2=False):
    workspace = Path(__file__).resolve().parents[4]
    demo_dir = workspace / ".tmp" / f"plan-demo-{uuid4().hex}"
    demo_dir.mkdir(parents=True)
    os.environ.update(
        {
            "DATABASE_PATH": str(demo_dir / "demo.db"),
            "UPLOAD_DIRECTORY": str(demo_dir / "uploads"),
            "JWT_SECRET": "isolated-demo-only-" + uuid4().hex,
            "APP_ENV": "simulated-plan-demo",
            "LLM_PROVIDER": "fake",
            "RETRIEVER_PROVIDER": "fake",
            "OPENAI_API_KEY": "",
            "PLAN_LLM_PROVIDER": "fake",
        }
    )
    from ...config import get_settings

    get_settings.cache_clear()
    from ...db import database
    from ...main import app
    from ...repositories.plans import PlanRepository
    from ...services.coach import CoachService, FakeNotification, get_coach_service
    from ...services.plans import PlanService, get_plan_service
    from .contract import MetricSnapshot
    from .llm import PlanSettings

    clock = [datetime.fromisoformat("2030-01-07T08:00:00+07:00")]
    plans = PlanService(
        PlanSettings(
            _env_file=None,
            llm_provider="fake",
            vision_adapter_key="SIMULATED-VISION-ONLY",
            catalog_path=None,
            metrics_path=None,
            coach_v2_enabled=coach_v2,
            variant_seed="1",  # Explicit deterministic synthetic demo; pair 1 belongs to AI.
            trace_provider="none",
        ),
        clock=lambda: clock[0],
    )

    class DemoMetrics:
        def load(self, pair_id):
            with database() as db:
                pair = db.execute("SELECT * FROM peer_matches WHERE id=?", (pair_id,)).fetchone()
                ids = [pair["user_a_id"], pair["user_b_id"]]
                repo = PlanRepository(db)
                versions = {uid: repo.active(pair_id, uid)["version"] for uid in ids}
            return MetricSnapshot(
                pair_id=pair_id,
                as_of=clock[0],
                source="SIMULATED_METRICS_NO_REAL_PILOT",
                plan_versions=versions,
                pacing={ids[0]: 0.6, ids[1]: 0.8},
                due_count={uid: 1 for uid in ids},
                last_checkin={uid: clock[0] - timedelta(days=3) for uid in ids},
            )

    coach = CoachService(plans, DemoMetrics(), FakeNotification())
    if coach_v2:
        from .graph import CoachSelector
        from .llm import FakeLLM

        coach.selector = CoachSelector(
            FakeLLM(
                [{"action": "replan", "message": "Bạn có thể xem phương án giảm tải và tự quyết định khi sẵn sàng."}]
            )
        )
    app.dependency_overrides[get_plan_service] = lambda: plans
    app.dependency_overrides[get_coach_service] = lambda: coach

    # This route exists only in this explicit localhost demo command, never in main.py.
    def advance():
        clock[0] += timedelta(days=2)
        return {"now": clock[0].isoformat(), "simulation": True}

    app.add_api_route("/__demo/advance", advance, methods=["POST"], include_in_schema=False)
    print("SIMULATED DEMO: new temporary DB, FakeLLM, fake metrics/check-in/notification, clock 2030. No real sends.")
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8015)
    parser.add_argument("--coach-v2", action="store_true", help="Exercise LangGraph with a single FakeLLM response")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a localhost development port 1024–65535")
    serve(args.port, args.coach_v2)


if __name__ == "__main__":
    main()
