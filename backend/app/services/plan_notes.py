from ..db import database, utc_now
from ..repositories.plans import PlanError, PlanRepository


def notes(pair_id, user, text=None):
    with database() as db:
        PlanRepository(db).pair(pair_id, user)
        db.execute("CREATE TABLE IF NOT EXISTS pb_plan_notes (id INTEGER PRIMARY KEY AUTOINCREMENT,pair_id INTEGER,user_id INTEGER,text TEXT,created_at TEXT)")
        if text is not None:
            text = text.strip()
            if not text:
                raise PlanError("EMPTY_NOTE", "Viết một lời nhắn trước khi gửi nhé.", 422)
            db.execute("INSERT INTO pb_plan_notes(pair_id,user_id,text,created_at) VALUES(?,?,?,?)",(pair_id,user["id"],text,utc_now()))
        rows = db.execute("SELECT n.id,n.user_id,p.display_name,n.text,n.created_at FROM pb_plan_notes n JOIN profiles p ON p.user_id=n.user_id WHERE n.pair_id=? ORDER BY n.id DESC LIMIT 30",(pair_id,)).fetchall()
        return {"items":[dict(r) for r in rows]}
