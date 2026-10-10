# PeerBridge backend

FastAPI, SQLite, LangGraph. Mọi API nằm dưới `/api/v1`; tài liệu tự sinh ở `/docs` khi chạy local.

Cách chạy và biến môi trường: xem [README gốc](../README.md) và [`.env.example`](.env.example). Kiến trúc: [ARCHITECTURE.md](../ARCHITECTURE.md).

## Thư mục `app/`

| Thư mục / file | Nội dung |
| --- | --- |
| `main.py`, `db.py`, `config.py`, `security.py` | Khởi động app, schema SQLite, cấu hình, JWT |
| `routers/`, `services/`, `repositories/` | Đăng nhập, hồ sơ, ghép cặp, kết nối, phiên học, kế hoạch |
| `onboarding/` | Danh mục concept (SQL, Python, 15 bài khóa AICB) và hồ sơ đã xác nhận |
| `matching/`, `services/matching_engine.py`, `services/match_ai.py` | Điểm ghép cặp và AI xếp lại |
| `agents/plan_coach/`, `services/plans.py`, `services/coach.py` | Kế hoạch tuần (LLM chia việc, code xếp lịch) và coach |
| `checkin/` | Check-in bằng ảnh (AI Vision, LangGraph), lưu ảnh, báo bạn cặp |
| `metrics/` | Đo pacing, chuỗi ngày, rủi ro bỏ cuộc của từng cặp |
| `loop/` | Vòng check-in → đo → coach → thông báo, trần chi phí AI chung (`ai_budget.py`) |
| `agents/moderator/` | Moderator phòng học: lọc trước, phân loại, gợi mở Socratic, RAG, chặn lộ đáp án |
| `session_review/` | Tóm tắt phiên và chấm phiên bằng LLM-as-judge |
| `home/` | Dữ liệu trang Tổng quan và thông báo trong app |
| `admin_roles.py`, `moderation_admin.py` | Quyền Admin và hàng đợi kiểm duyệt |
| `demo.py` | Chế độ demo: 36 bạn học mẫu, tài khoản Lan, Minh, Admin |

## Dữ liệu

- `data/concepts/`: `catalog.json` (danh mục concept chuẩn) và `plan_catalog.json` (việc cụ thể cho kế hoạch, tạo bằng
  `scripts/build_plan_catalog.py`).
- `data/courses/`: tài liệu cho RAG, xem [README](data/courses/README.md).
- Migration Alembic trong `alembic/versions/`; app cũng tự tạo bảng khi khởi động (`init_db`).

## Kiểm thử

```bash
python -m pytest -q tests
```

Test chỉ dùng provider giả (`fake`, `template`), không gọi OpenAI.
