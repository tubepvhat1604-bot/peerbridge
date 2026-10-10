# PeerBridge frontend

Next.js 16, React 19, TypeScript, PWA.

## Chạy local

```bash
npm install
npm run dev
```

Mở `http://localhost:3001`. Mặc định giao diện gọi backend tại `http://localhost:8000`; đổi bằng `NEXT_PUBLIC_API_URL` trong `.env.local`
(xem `.env.example`).

## Màn hình

- Trang giới thiệu, đăng nhập, "Vào thử" ở chế độ demo
- Tổng quan: việc hôm nay, tiến độ tuần, chuỗi ngày
- Tìm bạn học với điểm ghép cặp do backend tính, kết nối khi hai bên cùng đồng ý
- Kế hoạch tuần và check-in bằng ảnh
- Phòng học realtime có moderator gợi mở
- Admin: tổng quan, phiên học, hàng đợi kiểm duyệt

## Gọi API

Kiểu dữ liệu và lớp gọi REST/WebSocket nằm trong `lib/` (`api.ts`, `types.ts`, `plan-types.ts`...). Giao diện chỉ nói chuyện với
backend qua `/api/v1`, không gọi AI hay database trực tiếp.

## Kiểm tra

```bash
npx tsc --noEmit -p .
npm run build
```
