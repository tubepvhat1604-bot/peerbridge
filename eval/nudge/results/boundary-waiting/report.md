# Nudge — trạng thái quan sát 24 giờ

Nguồn: `synthetic_boundary_fixture`; simulation=True; mốc quan sát `2030-01-09T10:30:00+00:00`. Nguồn production chưa được xác nhận.

Trạng thái: **WAITING_24H**. SENT đủ điều kiện: 2; đã đủ 24h: 0; đang pending: 2; có completion đầu tiên trong 24h ở mẫu đủ thời gian: 0.

| Variant | SENT | Đủ 24h | Pending | Check-in trong 24h | Tỷ lệ trên mẫu đủ 24h |
| --- | --- | --- | --- | --- | --- |
| ai | 2 | 0 | 2 | 0 | null |

Trạng thái hiện được lưu của intervention đã tạo trước mốc: `{"SENT": 2, "SIMULATED": 1, "PENDING": 1, "NOT_CONFIGURED": 1, "FAILED": 1, "RESERVED": 1, "SUPPRESSED_QUIET_HOURS": 1}`. Đây không phải tái dựng lịch sử status tại cutoff.

Dưới 24h luôn pending kể cả đã phản hồi. Chỉ lần completed_at đầu tiên của cùng user/pair được tính; replay không tạo tiến độ mới. SIMULATED/FAILED/PENDING/RESERVED/NOT_CONFIGURED không vào cohort SENT. Mẫu số 0 có rate=null.

Đây là quan sát mô tả; phân nhóm parity ID không phải random experiment. Không ước lượng hiệu quả nhân quả hoặc điền điểm/pilot giả. Fixture SENT là acknowledgement synthetic, không phải thông báo thật.
