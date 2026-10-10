# PeerBridge

PeerBridge ghép cặp hai người tự học để cùng giữ nhịp học. Hai bạn tìm được người học hợp, cùng lập kế hoạch tuần, check-in bằng một tấm ảnh
mỗi buổi, học chung trong phòng có AI gợi mở theo kiểu Socratic, và được nhắc nhẹ khi một người chậm lại.

Dự án EDU-07 của nhóm P-005, chương trình AI20K Build Phase Cohort 4 (VinUniversity).

- Web: https://peerbridge-deploy.vercel.app
- API: https://peerbridge-api-4fht.onrender.com/health (gói miễn phí, lần đầu mở có thể chờ khoảng 1 phút)
- Dùng thử: bấm **Đăng nhập** rồi chọn **Vào thử: Lan**, **Vào thử: Minh** hoặc **Vào thử: Admin**, không cần mật khẩu.

![Kiến trúc PeerBridge](frontend/public/peerbridge-architecture.svg)

## Tính năng

| Phần | Người dùng thấy gì | AI làm gì |
| --- | --- | --- |
| Tìm bạn học | Danh sách bạn hợp nhất kèm lý do "vì sao hợp", gửi và nhận lời mời | Điểm máy (bài bổ trợ, giờ rảnh, mục tiêu), rồi LLM xếp lại nhóm đầu |
| Kế hoạch tuần | Mỗi người một kế hoạch riêng, việc 30–90 phút xếp đúng giờ rảnh | LLM chia việc theo danh mục concept; code giữ ngày giờ, thứ tự tiên quyết và giới hạn số phút cam kết |
| Check-in bằng ảnh | Chụp màn hình hoặc trang vở, AI ghi nhận việc vừa làm và báo bạn cặp | LangGraph và mô hình đọc ảnh; không chắc thì hỏi lại bằng 3 gợi ý |
| Nhịp học và coach | Tổng quan việc hôm nay, tuần này, chuỗi ngày cùng học; lời nhắc khi một bạn chậm | Đo pacing từng người; coach viết lời nhắc, tối đa 1 lần mỗi ngày, không nhắc 22:00–07:00 |
| Phòng học | Chat realtime, đồng hồ tập trung, nút "Kết thúc & tóm tắt" | Moderator LangGraph chặn xin đáp án, gợi mở từng bước, trích "(Xem bài …, slide N)" từ tài liệu môn học |
| Admin | Tổng quan, xem phiên học, hàng đợi kiểm duyệt, chấm phiên | LLM-as-judge chấm mức tuân thủ Socratic và việc có lộ đáp án hay không |

Mọi phần AI dùng chung một trần chi phí mỗi ngày (mặc định 2 USD, biến `VISION_DAILY_BUDGET_USD`). Khi hết trần hoặc gặp lỗi,
app tự chuyển về luật và mẫu có sẵn nên người dùng vẫn dùng tiếp được.

## Công nghệ

- Giao diện: Next.js 16, React 19, TypeScript, cài được như app (PWA). Chạy trên Vercel.
- Backend: FastAPI, Pydantic, LangGraph, SQLite (sao lưu tùy chọn bằng Litestream). Chạy trên Render.
- AI: OpenAI `gpt-4.1-mini` qua API tương thích OpenAI. RAG dùng BM25 trên markdown tài liệu môn học, không cần vector DB.

Chi tiết từng lớp và luồng dữ liệu ở [ARCHITECTURE.md](ARCHITECTURE.md). Cách đưa lên Render và Vercel ở [docs/DEPLOY.md](docs/DEPLOY.md).

## Chạy trên máy

Cần Python 3.11 trở lên và Node.js 20.9 trở lên.

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-deploy.txt
cp .env.example .env               # điền OPENAI_API_KEY nếu muốn dùng AI thật
DEMO_MODE=true python run.py       # http://127.0.0.1:8000/docs (PowerShell: $env:DEMO_MODE="true"; python run.py)
```

Giao diện (mở terminal khác):

```bash
cd frontend
npm ci
echo "NEXT_PUBLIC_API_URL=http://127.0.0.1:8000" > .env.local
npm run dev                        # http://localhost:3001
```

Trên Windows có sẵn `start-local.ps1` để chạy cả hai cùng lúc.

`DEMO_MODE=true` tạo 36 bạn học mẫu và các nút "Vào thử". Không có `OPENAI_API_KEY` thì app vẫn chạy: ghép cặp dùng điểm máy,
kế hoạch dùng mẫu, phòng học dùng luật.

### Tài liệu cho RAG

Repo này không kèm slide giảng viên khóa AICB vì nhóm không có quyền chia sẻ chúng. Nếu muốn AI phòng học trích nguồn từ tài liệu
của bạn, xem [backend/data/courses/README.md](backend/data/courses/README.md).

## Kiểm thử

```bash
cd backend && pip install -r requirements.txt && python -m pytest -q tests   # test backend, không gọi API thật
cd frontend && npx tsc --noEmit -p .              # kiểm tra kiểu
cd frontend/tests/api && npm ci && npm test       # test lớp gọi API
```

Bộ đánh giá AI (ghép cặp, kế hoạch, coach, AI Vision, moderator, đo nhịp học) nằm trong `eval/`. Mỗi thư mục có script chạy
và kết quả đã lưu.

## Nhóm

| Thành viên | Phần phụ trách |
| --- | --- |
| Tú | AI Vision (check-in ảnh), trang Tổng quan, vòng đo nhịp học và coach, chế độ demo, deploy |
| Chính | Danh mục concept, onboarding, ghép cặp, đo tiến độ (Data 1) |
| Sang | Kế hoạch tuần và coach (Data 2) |
| Nhóm nền tảng | Khung giao diện, đăng nhập, kết nối, phòng học và moderator |
