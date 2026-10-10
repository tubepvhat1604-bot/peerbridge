"""Read-only internal views over stored snapshots. No alternate measurement formulas."""

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

from .contracts import PairMetrics


def load_dashboard_rows(path: Path, *, since: date | None = None, until: date | None = None,
                        limit: int = 1000) -> list[dict[str, Any]]:
    if not 1 <= limit <= 10000:
        raise ValueError("Dashboard row limit must be between 1 and 10000")
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("Choose an existing metrics database; the dashboard never creates one")
    with closing(sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute(
            """SELECT m.payload FROM pair_metrics_daily m JOIN pairs p ON p.id=m.pair_id
               WHERE m.pair_started_at=p.started_at AND (? IS NULL OR m.date>=?) AND (? IS NULL OR m.date<=?)
               ORDER BY m.date DESC,m.pair_id LIMIT ?""",
            (since.isoformat() if since else None, since.isoformat() if since else None,
             until.isoformat() if until else None, until.isoformat() if until else None, limit)).fetchall()
    result = []
    for row in rows:
        metric = PairMetrics.model_validate_json(row[0])
        result.append({"pair_id": metric.pair_id, "study_date": metric.study_date.isoformat(),
                       "pacing_a": metric.pacing_a, "pacing_b": metric.pacing_b, "pair_score": metric.pair_score,
                       "gap": metric.gap, "risk_a": metric.risk_a.score, "risk_b": metric.risk_b.score,
                       "risk_observed_a": metric.risk_a.observed_weight, "risk_observed_b": metric.risk_b.observed_weight,
                       "streak": metric.streak, "needs_attention": metric.needs_attention,
                       "completed_minutes_a": metric.learner_a.completed_minutes,
                       "completed_minutes_b": metric.learner_b.completed_minutes,
                       "computed_at": metric.computed_at.isoformat(), "metric_version": metric.metric_version})
    return result


def render_dashboard(st: Any, path: Path) -> None:
    st.title("PeerBridge — Data 1 measurement (internal)")
    st.caption("Stored snapshots; synthetic fixtures do not demonstrate learner outcomes. Risk is a preliminary signal, not a probability.")
    try:
        rows = load_dashboard_rows(path)
    except (ValueError, sqlite3.Error) as error:
        st.error(str(error))
        return
    if not rows:
        st.info("No snapshots. Configure the authoritative Data 2/Vision adapter before computing production metrics.")
        return
    latest_day = rows[0]["study_date"]
    latest = [row for row in rows if row["study_date"] == latest_day]
    st.caption(f"Latest stored study day: {latest_day}. Display is bounded to 1000 snapshots; check computed_at for freshness.")
    st.subheader("Pair list / attention signals")
    attention_only = st.checkbox("Only pairs needing attention", value=False)
    st.dataframe([row for row in latest if not attention_only or row["needs_attention"]], hide_index=True)
    st.subheader("Pair score distribution")
    counts: dict[str, int] = {}
    for row in latest:
        label = f"{row['pair_score']:.2f}"
        counts[label] = counts.get(label, 0) + 1
    st.bar_chart([{"pair_score": label, "pairs": count} for label, count in sorted(counts.items())], x="pair_score", y="pairs")
    pair_id = st.selectbox("Pair history", sorted({row["pair_id"] for row in rows}))
    trend = sorted([row for row in rows if row["pair_id"] == pair_id], key=lambda row: row["study_date"])
    st.subheader("Pacing / pair score / gap / risk trends")
    st.line_chart(trend, x="study_date", y=["pacing_a", "pacing_b", "pair_score", "gap", "risk_a", "risk_b"])
    st.subheader("Finalized workload / streak history")
    st.dataframe(trend, hide_index=True)
