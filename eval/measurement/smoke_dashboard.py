"""Optional real Streamlit smoke test in a separate dashboard environment; temporary SQLite only."""

import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import streamlit  # noqa: E402
from app.db import SCHEMA as LEGACY_SCHEMA  # noqa: E402
from app.matching.schema import initialize_matching  # noqa: E402
from app.metrics.engine import compute_metrics  # noqa: E402
from app.metrics.repository import MetricsRepository  # noqa: E402
from app.metrics.schema import initialize_metrics  # noqa: E402
from run_phase2b import DAY, NOW, START, build_input  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402


def smoke():
    with TemporaryDirectory(prefix="peerbridge-dashboard-") as directory:
        path = Path(directory) / "synthetic.db"
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(LEGACY_SCHEMA)
            initialize_matching(conn)
            initialize_metrics(conn)
            for user_id in (1, 2):
                conn.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)",
                             (user_id, f"smoke-{user_id}@example.edu", "test", START.isoformat()))
            conn.execute("INSERT INTO connection_requests(id,requester_id,recipient_id,status,created_at) VALUES(1,1,2,'MATCHED',?)", (START.isoformat(),))
            conn.execute("INSERT INTO peer_matches(id,connection_request_id,user_a_id,user_b_id,created_at) VALUES(1,1,1,2,?)", (START.isoformat(),))
            conn.execute("""INSERT INTO pairs(id,user_a,user_b,match_level,match_reason,match_result,reranking,source,started_at,status)
                            VALUES(1,1,2,'complementary','synthetic','{}','{}','invitation',?,'active')""", (START.isoformat(),))
            case = {"id": "dashboard-smoke", "due": [100, 100], "credit": [20, 80]}
            MetricsRepository(conn).save(compute_metrics(build_input(case), DAY, NOW))
            conn.commit()
        os.environ["METRICS_DASHBOARD_DB"] = str(path)
        app = AppTest.from_file(str(ROOT / "backend/measurement_dashboard.py"), default_timeout=30).run()
        assert not app.exception and not app.error, str(app.exception)
        assert len(app.dataframe) == 2 and len(app.selectbox) == 1
        app.checkbox[0].check().run()
        assert not app.exception and len(app.dataframe[0].value) == 1
        os.environ["METRICS_DASHBOARD_DB"] = str(Path(directory) / "missing.db")
        app.run()
        assert not app.exception and len(app.error) == 1
        assert not Path(os.environ["METRICS_DASHBOARD_DB"]).exists()
    return {"streamlit_version": streamlit.__version__, "checks_passed": 3,
            "checks": ["stored synthetic snapshot rendered", "attention filter rendered", "missing DB fails without creation"],
            "production_data_used": False}


if __name__ == "__main__":
    report = smoke()
    Path(__file__).with_name("dashboard_smoke.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
