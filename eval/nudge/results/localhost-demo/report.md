# Nudge — trạng thái quan sát 24 giờ

Nguồn: `sqlite_read_only`; simulation=True; mốc quan sát `2030-01-10T08:00:00+07:00`. Nguồn production chưa được xác nhận.

Trạng thái: **NO_SUCCESSFUL_DELIVERIES**. SENT đủ điều kiện: 0; đã đủ 24h: 0; đang pending: 0; có completion đầu tiên trong 24h ở mẫu đủ thời gian: 0.

| Variant | SENT | Đủ 24h | Pending | Check-in trong 24h | Tỷ lệ trên mẫu đủ 24h |
| --- | --- | --- | --- | --- | --- |

Trạng thái hiện được lưu của intervention đã tạo trước mốc: `{"SIMULATED": 1}`. Đây không phải tái dựng lịch sử status tại cutoff.

Dưới 24h luôn pending kể cả đã phản hồi. Chỉ lần completed_at đầu tiên của cùng user/pair được tính; replay không tạo tiến độ mới. SIMULATED/FAILED/PENDING/RESERVED/NOT_CONFIGURED không vào cohort SENT. Mẫu số 0 có rate=null.

Đây là quan sát mô tả; phân nhóm parity ID không phải random experiment. Không ước lượng hiệu quả nhân quả hoặc điền điểm/pilot giả. Fixture SENT là acknowledgement synthetic, không phải thông báo thật.
