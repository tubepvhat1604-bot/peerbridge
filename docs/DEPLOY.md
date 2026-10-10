# Đưa PeerBridge lên mạng

Backend (thư mục `backend/`) chạy trên **Render**, giao diện (thư mục `frontend/`) chạy trên **Vercel**. Cả hai đều có gói miễn phí.

## 1. Backend trên Render (làm trước)

1. Vào https://render.com, đăng nhập bằng GitHub.
2. Bấm **New → Blueprint**, chọn repo này. Render đọc `render.yaml` và hiện dịch vụ `peerbridge-api` (nhánh `main`).
3. Điền các biến được hỏi:
   - `OPENAI_API_KEY`: key OpenAI. Để trống thì mọi phần AI chạy bằng luật và mẫu có sẵn.
   - `CORS_ORIGINS`: tạm điền `http://localhost:3001`, sửa lại ở bước 3.
   - `LITESTREAM_*`: để trống nếu chưa cần giữ dữ liệu (xem mục sao lưu bên dưới).
4. Bấm **Apply** và chờ build xong (khoảng 5 phút). Mở `https://<tên dịch vụ>.onrender.com/health`, thấy `"status":"ok"` là chạy.

Gói Free ngủ sau 15 phút không ai dùng; lần mở đầu tiên sau đó phải chờ 30–60 giây. Trước khi demo, mở `/health` một lần
cho server thức.

`backend/start.sh` đặt sẵn mặc định cho bản chạy thật: kế hoạch dùng AI chia việc, coach v2, AI xếp lại ghép cặp,
vòng đo mỗi 60 phút và `DEMO_MODE=true` (36 bạn học mẫu, nút "Vào thử"). Khi chạy với người thật, đặt `DEMO_MODE=false`
trên Render.

## 2. Giao diện trên Vercel

1. Vào https://vercel.com, đăng nhập bằng GitHub.
2. **Add New → Project → Import** repo này.
3. **Root Directory**: `frontend`. Framework tự nhận là Next.js.
4. **Environment Variables**: thêm `NEXT_PUBLIC_API_URL` = link Render ở bước 1 (không có `/` cuối).
5. Bấm **Deploy**.

## 3. Nối hai bên

Trên Render: `peerbridge-api` → **Environment** → sửa `CORS_ORIGINS` thành link Vercel (không có `/` cuối) → **Save**.
Render tự khởi động lại.

## Giữ dữ liệu trên gói Free: sao lưu lên Supabase

Database là SQLite trong ổ đĩa của server, nên mất khi server ngủ hoặc deploy lại. `backend/start.sh` dùng Litestream để sao lưu
liên tục lên một bucket S3 (ví dụ Supabase Storage) và tự lấy lại khi khởi động. Bật như sau:

1. Supabase: tạo project → **Storage** → tạo bucket riêng tư, ví dụ `peerbridge-backup`.
2. **Project Settings → Storage → S3 Connection**: bật và tạo access key.
3. Render → `peerbridge-api` → **Environment**: điền `LITESTREAM_BUCKET`, `LITESTREAM_ENDPOINT`
   (dạng `https://<mã>.supabase.co/storage/v1/s3`), `LITESTREAM_REGION`, `LITESTREAM_ACCESS_KEY_ID`,
   `LITESTREAM_SECRET_ACCESS_KEY`.
4. **Save, rebuild, and deploy**. Log khởi động có dòng `[start] Đang sao lưu liên tục lên ...` là đã bật.

## Tài liệu cho RAG

Repo công khai chỉ kèm `backend/data/courses/demo-course`. Muốn AI phòng học trích nguồn từ slide của bạn, tạo thư mục khóa học
theo [backend/data/courses/README.md](../backend/data/courses/README.md) và đặt `RAG_DEFAULT_COURSE_ID` trên Render.
