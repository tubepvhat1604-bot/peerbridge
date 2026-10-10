"""Chế độ demo (DEMO_MODE=true): vài chục bạn học mẫu để có gợi ý ghép cặp, và 2 tài khoản thử vào bằng một nút.

Bạn học mẫu không đăng nhập được (mật khẩu ngẫu nhiên), email đuôi @mau.peerbridge để lọc khi tính số liệu thực nghiệm.
Server khởi động lại thì tự nạp lại; chạy nhiều lần không tạo trùng.
"""
from __future__ import annotations

import json
import os
import random
import secrets

from fastapi import APIRouter, HTTPException

from .db import database, utc_now
from .schemas import TokenResponse
from .security import create_token, hash_password

SAMPLE_DOMAIN = "mau.peerbridge"
# Chủ đề theo 15 bài slide khóa AICB (cũng là tài liệu RAG trong data/courses/aicb), trùng tên concept domain "ai".
TOPICS = ["Nền tảng AI và LLM", "Bài toán kinh doanh cho AI", "Agent và ReAct", "Prompt Engineering và Tool Calling",
          "Context, Loop và Harness", "Tư duy sản phẩm AI và PRD", "Quản lý sản phẩm và dự án AI",
          "Embedding, Chunking và Vector Store", "RAG Pipeline", "Multi-Agent, MCP và LangGraph",
          "Data Pipeline và Observability", "Guardrails, HITL và Responsible AI", "Triển khai Agent lên Cloud",
          "Monitoring, Logging và Observability", "Đánh giá và Benchmark AI"]
FIRST = ["An", "Bảo", "Chi", "Dũng", "Giang", "Hà", "Hải", "Hiếu", "Hoa", "Huy", "Khánh", "Linh", "Long", "Mai",
         "Nam", "Ngọc", "Nhung", "Phong", "Phương", "Quân", "Quỳnh", "Sơn", "Tâm", "Thảo", "Thắng", "Trang", "Trung",
         "Tú", "Tuấn", "Uyên", "Việt", "Vy", "Yến", "Đức", "Hằng", "Kiên"]
LAST = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi", "Đỗ", "Ngô"]
SCHOOLS = ["ĐH Bách khoa Hà Nội", "ĐH Kinh tế Quốc dân", "ĐH Ngoại thương", "ĐH Công nghệ - ĐHQGHN",
           "Học viện Bưu chính Viễn thông", "ĐH Khoa học Tự nhiên TP.HCM", "ĐH Kinh tế TP.HCM", "ĐH FPT"]
MAJORS = ["Phân tích dữ liệu", "Kinh tế", "Marketing", "Công nghệ thông tin", "Tài chính", "Hệ thống thông tin"]
CITIES = ["Hà Nội", "TP.HCM", "Đà Nẵng"]
GOALS = {
    "Nền tảng AI và LLM": "Hiểu token, context window, temperature để dùng LLM đúng cách",
    "Bài toán kinh doanh cho AI": "Chọn được bài toán kinh doanh đáng làm bằng AI và mức tự động hóa phù hợp",
    "Agent và ReAct": "Tự dựng được agent ReAct đơn giản có gọi tool",
    "Prompt Engineering và Tool Calling": "Viết system prompt rõ ràng và khai báo tool calling cho agent",
    "Context, Loop và Harness": "Thiết kế context, vòng lặp và harness bao quanh model",
    "Tư duy sản phẩm AI và PRD": "Viết PRD cho một tính năng AI có tiêu chí thành công rõ ràng",
    "Quản lý sản phẩm và dự án AI": "Lập kế hoạch và quản lý rủi ro cho dự án AI của nhóm",
    "Embedding, Chunking và Vector Store": "Chọn cách chunking và embedding phù hợp, lưu vào vector store",
    "RAG Pipeline": "Dựng RAG Pipeline trả lời có trích nguồn từ tài liệu môn học",
    "Multi-Agent, MCP và LangGraph": "Cho nhiều agent phối hợp bằng LangGraph và MCP",
    "Data Pipeline và Observability": "Giữ pipeline nạp tài liệu chạy ổn và phát hiện lỗi sớm",
    "Guardrails, HITL và Responsible AI": "Thêm guardrail và bước người duyệt để agent an toàn",
    "Triển khai Agent lên Cloud": "Đưa agent từ laptop lên cloud có URL chạy thật",
    "Monitoring, Logging và Observability": "Theo dõi log và chỉ số của agent sau khi deploy",
    "Đánh giá và Benchmark AI": "Dựng bộ đánh giá để đo chất lượng agent một cách khoa học",
}
EVENINGS = [("19:00", "21:00"), ("20:00", "22:00"), ("18:30", "20:30"), ("07:00", "09:00"), ("13:30", "15:30")]

# Hai tài khoản thử, bổ trợ nhau: Lan cần RAG và Embedding, giỏi Prompt và Agent; Minh ngược lại.
# Rảnh mọi ngày 07:00-23:00 để kế hoạch luôn có việc ngay hôm nay: demo lúc nào cũng check-in được và thấy số nhảy.
DEMO_ACCOUNTS = {
    "lan": {"name": "Lan", "need": ["RAG Pipeline", "Embedding, Chunking và Vector Store"],
            "offer": ["Prompt Engineering và Tool Calling", "Agent và ReAct"],
            "school": "ĐH Kinh tế Quốc dân", "major": "Phân tích dữ liệu"},
    "minh": {"name": "Minh", "need": ["Prompt Engineering và Tool Calling", "Agent và ReAct"],
             "offer": ["RAG Pipeline", "Embedding, Chunking và Vector Store"],
             "school": "ĐH Bách khoa Hà Nội", "major": "Công nghệ thông tin"},
}
DEMO_DAYS = tuple(range(7))
DEMO_HOURS = ("07:00", "23:00")
# Tài khoản thử vai trò Admin: xem mọi phiên học, log kiểm duyệt và dashboard.
DEMO_ADMIN_SLUG = "admin"
DEMO_ADMIN_NAME = "Admin"


def enabled() -> bool:
    return os.environ.get("DEMO_MODE", "false").lower() == "true"


def _insert_learner(db, email, name, school, major, city, need, offer, slots, bio):
    now = utc_now()
    uid = db.execute(
        "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
        (email, hash_password(secrets.token_urlsafe(24)), now),
    ).lastrowid
    _write_learning(db, uid, name, school, major, city, need, offer, slots, bio, now)
    return uid


def _sync_learner(db, uid, name, school, major, city, need, offer, slots, bio):
    """Database cũ còn chủ đề mẫu đời trước (SQL, Python...): ghi lại chủ đề, mục tiêu, giờ rảnh cho khớp bản hiện tại."""
    needs = sorted(r["topic"] for r in db.execute("SELECT topic FROM help_needs WHERE profile_user_id=?", (uid,)))
    offers = sorted(r["topic"] for r in db.execute("SELECT topic FROM help_offers WHERE profile_user_id=?", (uid,)))
    windows = sorted((r["day_of_week"], r["start_time"][:5], r["end_time"][:5]) for r in db.execute(
        "SELECT day_of_week, start_time, end_time FROM availability WHERE profile_user_id=?", (uid,)))
    if needs == sorted(need) and offers == sorted(offer) and windows == sorted((d, a, b) for d, (a, b) in slots):
        return False
    for table in ("help_needs", "help_offers", "availability"):
        db.execute(f"DELETE FROM {table} WHERE profile_user_id=?", (uid,))
    _write_learning(db, uid, name, school, major, city, need, offer, slots, bio, utc_now())
    return True


def _write_learning(db, uid, name, school, major, city, need, offer, slots, bio, now):
    db.execute(
        """INSERT INTO profiles(user_id, display_name, age, city, occupation, bio, school, major, subjects,
               learning_goals, intent, interests, available_times, updated_at)
           VALUES (?, ?, ?, ?, 'Sinh viên', ?, ?, ?, ?, ?, 'conversation', '[]', '[]', ?)
           ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name, city=excluded.city, bio=excluded.bio,
             school=excluded.school, major=excluded.major, subjects=excluded.subjects,
             learning_goals=excluded.learning_goals, updated_at=excluded.updated_at""",
        (uid, name, 19 + uid % 5, city, bio, school, major, json.dumps(need + offer, ensure_ascii=False),
         json.dumps([GOALS[t] for t in need], ensure_ascii=False), now),
    )
    for t in need:
        db.execute("INSERT INTO help_needs(profile_user_id, topic, current_level, target_outcome, created_at, updated_at)"
                   " VALUES (?, ?, 'Mới bắt đầu', ?, ?, ?)", (uid, t, GOALS[t], now, now))
    for t in offer:
        db.execute("INSERT INTO help_offers(profile_user_id, topic, proficiency_level, created_at, updated_at)"
                   " VALUES (?, ?, 'Khá', ?, ?)", (uid, t, now, now))
    for day, (start, end) in slots:
        db.execute("INSERT INTO availability(profile_user_id, day_of_week, start_time, end_time, timezone, created_at,"
                   " updated_at) VALUES (?, ?, ?, ?, 'Asia/Ho_Chi_Minh', ?, ?)", (uid, day, start, end, now, now))


def seed_demo(count: int = 36) -> int:
    """Nạp bạn học mẫu và 2 tài khoản thử nếu chưa có. Trả về số tài khoản vừa tạo."""
    rng = random.Random(2026)
    created = 0
    with database() as db:
        for i in range(count):
            email = f"hocvien{i + 1:02d}@{SAMPLE_DOMAIN}"
            name = f"{rng.choice(LAST)} {FIRST[i % len(FIRST)]}"
            need = rng.sample(TOPICS, rng.choice((1, 2)))
            offer = rng.sample([t for t in TOPICS if t not in need], rng.choice((1, 2)))
            days = rng.sample(range(7), 3)
            slot = rng.choice(EVENINGS)
            school, major, city = rng.choice(SCHOOLS), rng.choice(MAJORS), rng.choice(CITIES)
            bio = f"Muốn học {', '.join(need)} cùng bạn; có thể giúp {', '.join(offer)}."
            args = (name, school, major, city, need, offer, [(d, slot) for d in days], bio)
            if row := db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
                _sync_learner(db, row["id"], *args)
                continue
            _insert_learner(db, email, *args)
            created += 1
        for slug, a in DEMO_ACCOUNTS.items():
            email = f"{slug}@demo.peerbridge"
            bio = f"Tài khoản thử để demo. Cần {', '.join(a['need'])}, giúp được {', '.join(a['offer'])}."
            args = (a["name"], a["school"], a["major"], "Hà Nội", a["need"], a["offer"],
                    [(d, DEMO_HOURS) for d in DEMO_DAYS], bio)
            if row := db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
                _sync_learner(db, row["id"], *args)
                continue
            _insert_learner(db, email, *args)
            created += 1
        created += _ensure_demo_admin(db)
    return created


def _ensure_demo_admin(db) -> int:
    from .admin_roles import ADMIN_ROLE

    email = f"{DEMO_ADMIN_SLUG}@demo.peerbridge"
    if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        return 0
    now = utc_now()
    uid = db.execute("INSERT INTO users(email, role, password_hash, created_at) VALUES (?, ?, ?, ?)",
                     (email, ADMIN_ROLE.value, hash_password(secrets.token_urlsafe(24)), now)).lastrowid
    db.execute("""INSERT INTO profiles(user_id, display_name, age, city, occupation, intent, interests, available_times,
                      updated_at) VALUES (?, ?, 30, 'Hà Nội', 'Admin', 'conversation', '[]', '[]', ?)""",
               (uid, DEMO_ADMIN_NAME, now))
    return 1


router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("")
def demo_info():
    accounts = [{"slug": s, "name": a["name"]} for s, a in DEMO_ACCOUNTS.items()]
    return {"enabled": enabled(), "accounts": [*accounts, {"slug": DEMO_ADMIN_SLUG, "name": DEMO_ADMIN_NAME}]}


@router.post("/login/{slug}", response_model=TokenResponse)
def demo_login(slug: str) -> TokenResponse:
    if not enabled() or (slug not in DEMO_ACCOUNTS and slug != DEMO_ADMIN_SLUG):
        raise HTTPException(404, "Không có tài khoản thử")
    with database() as db:
        row = db.execute("SELECT id FROM users WHERE email=?", (f"{slug}@demo.peerbridge",)).fetchone()
    if row is None:
        seed_demo()
        with database() as db:
            row = db.execute("SELECT id FROM users WHERE email=?", (f"{slug}@demo.peerbridge",)).fetchone()
    return TokenResponse(access_token=create_token(row["id"]), user_id=row["id"])
