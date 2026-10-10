# AI Vision: check-in bằng ảnh

Người học chụp ảnh (hoặc gõ ghi chú) lúc học. AI đoán đang học concept nào trong plan, tự đánh dấu mục plan đã xong
hoặc hỏi lại khi không chắc. Bạn cặp thấy ảnh, câu tóm tắt và câu cầu nối ("Phần này bạn mạnh, có thể chỉ Minh vài phút").

## Nối với các phần khác

Mọi chỗ đọc dữ liệu của người khác nằm trong `actions.py`.

| Cần | Lấy từ | Dùng để |
| --- | --- | --- |
| Cặp đang active | Data 1: `pairs`, `pair_memberships` | Biết bạn cặp, phân quyền xem ảnh |
| Tên hiển thị | `profiles.display_name` | Hiển thị, câu tóm tắt |
| Mục plan đang mở | Data 2: plan ACTIVE trong `pb_plans` (qua `PlanRepository`) | Đưa concept vào prompt, hiện lựa chọn |
| Tên concept | Data 1: bảng `concepts` | Prompt và giao diện |
| Điểm mạnh của bạn cặp | Data 1: `user_concepts` (`role='offer'`, `theta >= 0.5`) | Câu cầu nối |
| Pacing | Data 1: `pair_metrics_daily` (chưa có thì tự tính từ plan) | Thanh tiến độ trong feed |
| Đánh dấu xong | Data 2: `PlanService.complete(CompletionEvent)` | Vision không tự sửa bảng plan |

Chỉ mục plan **đã tới giờ** (`scheduled_start <= now`) mới được đề xuất, vì Data 2 từ chối check-in trước giờ đã xếp.

Bảng của Vision: `vi_checkins`, `vi_reactions`, `vi_nudges` (tạo trong `init_db`; Postgres dùng migration
`20261006_0011_vision_checkins`). `vi_checkins` có `status`, `plan_item_id`, `user_corrected`, `confidence`, `cost_usd`...
để Data 1 tính pacing và để chấm AI.

## API (prefix `/api/v1`, cần Bearer token)

| Method | Endpoint | Việc |
| --- | --- | --- |
| POST | `/checkins` | multipart: `id` (UUID client tạo), `image`, `note` (tùy chọn) → 202, AI chạy nền |
| POST | `/checkins/text` | JSON `{id, note}` |
| GET | `/checkins/{id}` | Trạng thái + kết quả. Giao diện hỏi lại mỗi 2 giây tới khi hết `processing` |
| POST | `/checkins/{id}/confirm` | `{plan_item_id}`, hoặc `{plan_item_id: null}` = "mình học thứ khác" |
| POST | `/checkins/{id}/reactions` | `{emoji}` (bấm lại = bỏ) hoặc `{comment}` |
| GET | `/pairs/me/feed` | Dữ liệu trang chủ cặp: tiến độ, streak, check-in mới nhất |
| POST | `/pairs/{pair_id}/nudge` | Nút "Nhắc bạn mình" |
| GET | `/checkins/media/{path}` | Ảnh, có kiểm tra quyền (bạn cặp chỉ xem khi check-in đã `done`) |

Trạng thái: `processing` → `done` | `needs_confirm` | `not_study` | `failed`. Trừ `processing`, mọi trạng thái chưa xong
đều cho người dùng tự chọn mục, nên không bao giờ bị kẹt.

## Cấu hình (`.env`)

| Biến | Mặc định | Ghi chú |
| --- | --- | --- |
| `VISION_LLM_PROVIDER` | `fake` | `openai` để gọi thật. `fake` không gọi mạng; gõ `#low`, `#multi`, `#notstudy`, `#fail` vào ghi chú để thử từng trạng thái |
| `OPENAI_API_KEY` | | Dùng chung key của app (hoặc đặt `VISION_OPENAI_API_KEY` riêng) |
| `VISION_VISION_MODEL` | `gpt-4.1-mini` | Model đọc ảnh |
| `VISION_CONFIDENCE_HIGH` / `VISION_CONFIDENCE_LOW` | `0.75` / `0.40` | Chỉnh sau khi chạy eval |
| `VISION_STORAGE_DIR` | `<data>/checkin_images` | Ngoài thư mục `/uploads` công khai |

## Eval

```bash
python eval/vision/make_samples.py
python eval/vision/run_eval.py --labels eval/vision/labels.synthetic.csv --provider fake
python eval/vision/run_eval.py --labels eval/vision/labels.csv --models gpt-4.1-mini,gpt-5-mini
```

Ảnh thật để vào `eval/vision/images/real/` (không commit), nhãn ở `eval/vision/labels.csv`.
Mục tiêu (CONTEXT.md 8.5): đúng concept top-1 ≥ 75%, hỏi lại ≤ 30%, bắt ảnh không học ≥ 80%, p90 < 15 giây.

## Còn để mở

- Thông báo cho bạn cặp đang chỉ ghi log (`notify.py`). Nối vào kênh thông báo của app khi SE/PO có.
- Giao diện check-in trong `frontend/` chưa làm.
- Đưa check-in vào nguồn đo của Data 1 (`metrics/adapters.py`, `FinalizedCheckin`).
