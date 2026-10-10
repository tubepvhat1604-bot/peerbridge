"""Observational reminder report. Only SENT deliveries enter the 24-hour cohort."""

from datetime import UTC, datetime, timedelta


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Delivery and completion timestamps require timezone offsets")
    return parsed.astimezone(UTC)


def reminder_report(db, as_of):
    if as_of.utcoffset() is None:
        raise ValueError("Observation cutoff requires a timezone offset")
    attempts = db.execute("""SELECT i.id,i.pair_id,i.user_id,i.variant,i.action,a.created_at AS sent_at
        FROM pb_interventions i JOIN pb_delivery_attempts a ON a.intervention_id=i.id
        WHERE i.delivery_status='SENT' AND a.status='SENT'""").fetchall()
    # ISO strings with different offsets do not sort chronologically in SQLite MIN().
    first_sends = {}
    for row in attempts:
        sent = timestamp(row["sent_at"])
        previous = first_sends.get(row["id"])
        if previous is None or sent < previous[0]:
            first_sends[row["id"]] = (sent, row)
    observations = []
    for sent, row in sorted(first_sends.values(), key=lambda entry: (entry[0], entry[1]["id"])):
        if sent > as_of:
            continue
        until = sent + timedelta(hours=24)
        checkins = db.execute(
            """SELECT completed_at FROM pb_plan_items
            WHERE pair_id=? AND user_id=? AND completed_at IS NOT NULL""",
            (row["pair_id"], row["user_id"]),
        ).fetchall()
        # First completion is authoritative; replay events do not create new progress.
        responded = any(sent <= timestamp(e["completed_at"]) <= min(until, as_of) for e in checkins)
        observations.append(
            {
                "intervention_id": row["id"],
                "variant": row["variant"],
                "action": row["action"],
                "sent_at": sent.isoformat(),
                "observed_checkin": responded,
                "status": "pending" if as_of < until else "responded" if responded else "no_checkin_24h",
            }
        )
    eligible = [o for o in observations if o["status"] != "pending"]
    by_variant = {}
    for variant in sorted({o["variant"] for o in observations}):
        group = [o for o in observations if o["variant"] == variant]
        matured = [o for o in group if o["status"] != "pending"]
        responded = sum(o["status"] == "responded" for o in matured)
        by_variant[variant] = {
            "sent_count": len(group),
            "matured_count": len(matured),
            "pending_count": len(group) - len(matured),
            "checkin_24h_count": responded,
            "checkin_24h_rate": responded / len(matured) if matured else None,
        }
    return {
        "as_of": as_of.isoformat(),
        "sent_count": len(observations),
        "matured_count": len(eligible),
        "pending_count": len(observations) - len(eligible),
        "checkin_24h_count": sum(o["status"] == "responded" for o in eligible),
        "by_variant": by_variant,
        "attribution": "First confirmed completion for the same user and pair; descriptive association only.",
        "observations": observations,
        "interpretation": "Quan sát mô tả, không kết luận nhân quả; chỉ SENT được tính đã gửi. PENDING/RESERVED/SIMULATED/FAILED/NOT_CONFIGURED bị loại.",
    }
