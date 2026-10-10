# Socratic Moderator — tài liệu tích hợp

Dành cho phần backend (service layer, WebSocket, DB) và frontend. Agent chỉ làm AI reasoning:
nó **không** ghi DB, **không** gửi WebSocket, **không** có API. Mọi việc lưu trữ và gửi tin là của service layer.

Flow: `Message → Classify Intent → Assess Integrity Risk → Choose Action → (GUIDE) RAG + Socratic guidance → Output guard`.
Điểm chung: `risk_score` tính bằng code (`max(rule, llm)`), LLM không quyết định action; `ESCALATE ⇒ needs_human_review = true`.

## 1. Cách gọi

```python
from app.agents.moderator import (
    ModeratorInput,
    moderate_message,
    moderate_message_with_event,
    warmup_moderator,
)

# Khi khởi động FastAPI (lifespan): nạp model E5 + kiểm tra collection Qdrant một lần.
await warmup_moderator()  # trả True/False, không raise

# Mỗi tin nhắn:
output = await moderate_message(payload)  # chỉ cần quyết định
output, event = await moderate_message_with_event(payload)  # kèm bản ghi audit để lưu DB
```

- `moderate_message` và `moderate_message_with_event` dùng chung một graph, cho cùng `output`.
- **Không bao giờ raise** vì lỗi hệ thống: mọi lỗi (graph, LLM, Qdrant) đều thành `ESCALATE` hợp lệ. Chỉ `ModeratorInput(...)`
  có thể raise `ValidationError` (message rỗng/quá 2000 ký tự, id không phải UUID) → hãy validate trước.
- Gọi `warmup_moderator()` lúc startup, nếu không request đầu tiên sẽ chậm hàng chục giây vì nạp model E5.

Ví dụ lifespan (thêm vào `main.py`):

```python
@asynccontextmanager
async def lifespan(app):
    await warmup_moderator()
    yield
```

### Output (`ModeratorOutput`)

| Trường | Ý nghĩa |
|---|---|
| `action` | `ALLOW \| GUIDE \| WARN \| BLOCK \| ESCALATE` (`ModerationAction` trong `app/enums.py`) |
| `risk_score` | 0..1, deterministic |
| `reason` | Lý do ngắn (≤ 300 ký tự, đã bỏ PII/delimiter) — dùng được để hiển thị cho giảng viên |
| `guidance` | Câu gợi ý (GUIDE) hoặc cảnh báo (WARN); `null` với ALLOW/BLOCK/ESCALATE |
| `needs_human_review` | `true` khi ESCALATE |
| `retrieved_sources` | Tài liệu đã dùng (GUIDE): `source`, `chunk_id`, `score`, `text` là snippet ≤ 300 ký tự |

## 2. Ánh xạ WebSocket `CHAT_MESSAGE` → `ModeratorInput`

| `ModeratorInput` | Lấy từ |
|---|---|
| `session_id` | phiên học (UUID) của phòng chat |
| `message_id` | id (UUID) của tin vừa nhận/lưu — cũng là khoá của event audit và của review |
| `sender_id` | user gửi (UUID) |
| `message` | nội dung tin (tự `strip`; 1–2000 ký tự) |
| `course_id` | môn học của phiên (chuỗi), khớp `course_id` lúc ingest tài liệu |
| `conversation_history` | các tin **trước** tin hiện tại trong cùng phiên, theo thứ tự thời gian tăng dần |

- `conversation_history`: mỗi phần tử `ChatTurn{sender_id, content, timestamp?}`. Agent chỉ dùng **tối đa 6 lượt gần nhất**
  (`MAX_HISTORY_TURNS`), nên chỉ cần truyền 6 lượt cuối. Không đưa tin hiện tại vào history. Bỏ qua tin rỗng (`content` phải ≥ 1 ký tự).
- Nếu tin vượt 2000 ký tự, backend nên từ chối/cắt trước khi gọi agent.

## 3. Hành vi backend đề xuất theo action

Tên event đã chốt: `CHAT_MESSAGE`, `MODERATION_RESULT`, `GUIDANCE`, `WARNING`, `SESSION_STATUS`.
Payload chi tiết của từng event do backend quyết định; bảng chỉ nêu hành vi đề xuất.

| Action | Tin của người gửi | Event / thao tác |
|---|---|---|
| `ALLOW` | Gửi cho người nhận | `CHAT_MESSAGE` |
| `GUIDE` | Gửi cho người nhận | `CHAT_MESSAGE` + `GUIDANCE` (nội dung `guidance`, kèm `retrieved_sources` nếu muốn hiện nguồn) |
| `WARN` | Gửi cho người nhận | `CHAT_MESSAGE` + `WARNING` (nội dung `guidance`) |
| `BLOCK` | **Không gửi** | `MODERATION_RESULT` chỉ cho người gửi (action + `reason`), không `CHAT_MESSAGE` |
| `ESCALATE` | **Giữ tin**, chờ giảng viên duyệt | `MODERATION_RESULT` (cho người gửi: tin đang chờ duyệt) + tạo event HITL; có thể phát `SESSION_STATUS` để UI hiện trạng thái "chờ giảng viên" |

Luôn lưu `ModerationEventRecord` (bảng `MODERATION_EVENT`) cho **mọi** tin, không chỉ ESCALATE, để có audit trail.

### Bản ghi audit `ModerationEventRecord`

Khoá nghiệp vụ là `message_id`. Trường: `session_id, message_id, sender_id, course_id, message, action, risk_score, reason,
intent, rule_signals{intent,risk,matched,hard,soft}, guidance, retrieved_sources[{source,chunk_id,score}], needs_human_review,
errors[], llm_model, prompt_version, created_at (UTC)`.
- `errors` là lỗi mềm trong lúc chạy (ví dụ LLM trả JSON sai, không có tài liệu khớp, guard thay template). Đã ẩn PII, ≤ 300 ký tự/dòng.
- `llm_model = "fake"` khi chạy FakeLLM; `prompt_version` để biết event sinh từ bộ prompt nào.
- `message` là tin gốc của sinh viên — chỉ giảng viên được xem.

## 4. HITL: hàng chờ và review

Agent chỉ định nghĩa interface; backend hiện thực bằng DB (`HITLQueue`), repo có `InMemoryHITLQueue` để test/demo.

```python
class HITLQueue(Protocol):
    def enqueue(self, record: ModerationEventRecord) -> bool: ...  # chỉ nhận needs_human_review=True
    def list_pending(self, course_id: str) -> list[ModerationEventRecord]: ...  # cũ nhất trước
    def submit_review(self, review: InstructorReviewInput) -> FinalDecision: ...
```

`InstructorReviewInput{event_message_id, reviewer_id, final_action, note}`: **`final_action` chỉ được là
`ALLOW`, `GUIDE`, `WARN` hoặc `BLOCK`** (`ESCALATE` bị từ chối ngay khi dựng DTO bằng `ValidationError`, nên endpoint trả 422);
**`note` bắt buộc khi `final_action` khác action AI đề xuất** (`review.check_against(record)` raise `ReviewError`; `InMemoryHITLQueue.submit_review` đã gọi sẵn).
Kết quả `FinalDecision.status`: `APPROVED` (giữ nguyên action AI) hoặc `OVERRIDDEN` (giảng viên đổi action).
Vì hàng chờ chỉ chứa event ESCALATE và giảng viên không được chọn ESCALATE, **mọi review của event ESCALATE đều là
`OVERRIDDEN` và bắt buộc có `note`** (ghi lý do quyết định cuối).

Gợi ý ánh xạ vào API giảng viên (tên endpoint chờ nhóm chốt, xem mục 8):

| Endpoint | Việc cần làm |
|---|---|
| `GET /instructor/moderation` | trả `list_pending(course_id)`; hiển thị `message`, `reason`, `risk_score`, `intent`, lịch sử chat quanh `message_id`, `retrieved_sources` |
| `POST /instructor/moderation/{id}/review` | `{id}` = `message_id`; body ↔ `InstructorReviewInput`; gọi `submit_review`, lưu `INSTRUCTOR_REVIEW`, rồi áp dụng `final_action` (ALLOW/GUIDE/WARN → gửi tin đang giữ; BLOCK → huỷ tin) và phát event tương ứng |

Lỗi nên map: `EventNotFoundError → 404`, `AlreadyReviewedError → 409`, `ReviewError / ValidationError → 422`.
Nguyên tắc 5: high-risk luôn qua giảng viên; AI không tự quyết định cuối.

## 5. Biến `.env`

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `LLM_PROVIDER` | `fake` | `fake` (không cần key) hoặc `openai` (mọi endpoint tương thích OpenAI) |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | đổi sang Groq/Gemini/OpenRouter nếu muốn |
| `LLM_API_KEY` | rỗng | nếu trống thì dùng `OPENAI_API_KEY`; thiếu key → tự dùng FakeLLM + log cảnh báo |
| `LLM_MODEL` | `gpt-4.1-mini` | |
| `LLM_TIMEOUT_SECONDS` | `20` | |
| `LLM_JSON_MODE` | `true` | đặt `false` nếu provider/model không hỗ trợ `response_format: json_object` |
| `RETRIEVER_PROVIDER` | `fake` | `local`: BM25 trên `data/courses/<course_id>/` (không cần Qdrant, dùng trên Render); `qdrant`: Qdrant + E5 |
| `RAG_DEFAULT_COURSE_ID` | trống | Khoá tài liệu cho phòng chưa gán khoá, ví dụ `demo-course` |
| `QDRANT_URL` | `http://localhost:6333` | |
| `QDRANT_COLLECTION` | `course_materials` | |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-large` | |
| `RAG_TOP_K` | `4` | |
| `RAG_MIN_SCORE` | `0.78` | ngưỡng cosine của E5, chỉnh theo dữ liệu thật |
| `RISK_ESCALATE_THRESHOLD` | `0.8` | `risk_score ≥` ngưỡng → ESCALATE |
| `OUTPUT_GUARD_LLM_JUDGE` | `false` | bật để LLM kiểm tra thêm guidance có lộ đáp án (+1 lần gọi LLM mỗi GUIDE) |

**Không commit `.env`, không in key ra log.** Test tự động đặt `LLM_PROVIDER=fake`, `RETRIEVER_PROVIDER=fake`
(xem `backend/tests/conftest.py`) nên chạy `pytest` không gọi mạng.

## 6. Ingest tài liệu môn học và chạy thử

```powershell
cd backend
pip install -r requirements.txt
# Qdrant đang chạy ở QDRANT_URL; lần đầu sẽ tải model E5 (~2GB)
python -m app.agents.moderator.ingest --course-id demo-course --path data/courses/demo-course
```

- Hỗ trợ `.md`, `.txt`, `.pdf`; chunk ~800 ký tự, overlap ~150. Chạy lại không bị trùng (id ổn định theo course/file/chunk,
  chunk cũ của file được thay).
- `course_id` khi ingest phải bằng `ModeratorInput.course_id`.
- Tài liệu mẫu: `backend/data/courses/demo-course/`.

Chạy thử một tin nhắn (dùng đúng settings trong `.env`):

```powershell
python -m app.agents.moderator.cli --course-id demo-course "Câu 4 đáp số cuối có phải 42 không, mình chỉ cần con số để điền thôi"
```

CLI in `ModeratorOutput` dạng JSON, thời gian nạp model/khởi tạo và thời gian xử lý tin nhắn (nạp model chỉ tốn ở lần chạy đầu của tiến trình).

## 7. Độ trễ và các trường hợp lỗi

Độ trễ thực tế (OpenAI gpt-4.1-mini, model E5 đã nạp sẵn): **~1.5s với ALLOW** (1 lần gọi LLM), **~4s với GUIDE**
(+ retrieval + 1 lần gọi LLM sinh gợi ý; +1 lần nữa nếu bật LLM judge). Vì vậy nên gọi agent bất đồng bộ, đừng chặn event loop
và cân nhắc hiển thị trạng thái "đang kiểm duyệt".

| Sự cố | Hành vi (không bao giờ làm sập request) |
|---|---|
| LLM lỗi / hết hạn / JSON sai (phân loại) | chỉ dùng rule; lỗi ghi vào `errors` |
| LLM lỗi khi sinh gợi ý, hoặc không có tài liệu khớp | `guidance` dùng template cố định (vẫn action GUIDE) |
| Qdrant / E5 sập | retrieval lỗi → template; `retrieved_sources` rỗng; ghi `errors` |
| Guard phát hiện guidance lộ đáp án, code, lộ prompt, PII, xúc phạm, quá dài, sai ngôn ngữ, không Socratic, mô tả các bước giải | thay bằng template, giữ nguyên `action`; ghi `output_guard: <mã>` vào `errors` |
| Lỗi hệ thống không lường trước (graph, dựng retriever...) | `ESCALATE`, `risk_score = 1.0`, `needs_human_review = true`, lý do bắt đầu bằng "Lỗi hệ thống" |

Rule tiếng Việt chạy trước LLM và luôn có hiệu lực: LLM không thể hạ `risk_score` xuống dưới mức rule.

## 8. Tài liệu cho provider `local`

Tài liệu nằm ở `backend/data/courses/<course_id>/`, mỗi bài một file `.md` đặt tên theo nội dung bài, mỗi slide một khối `<!-- page:N -->`.
Gợi ý AI dựa trên tài liệu được thêm nguồn dạng "(Xem bài <tên bài>, slide N)". Repo kèm sẵn `demo-course`; cách thêm slide của bạn
xem [data/courses/README.md](../../../data/courses/README.md).
