# Nudge — kết quả bàn giao

Phân tích đã chạy ngày 06/10/2026 bằng runner read-only. Tách dữ liệu có nguồn từ HTTP smoke khỏi fixture kiểm tra biên; cả hai đều là mô phỏng, không có pilot production.

| Nguồn / cutoff | SENT đủ điều kiện | Đủ 24h | Pending | Completion trong mẫu đủ 24h | Trạng thái |
| --- | --- | --- | --- | --- | --- |
| DB demo localhost, 10/01/2030 08:00 +07 | 0 | 0 | 0 | 0 | NO_SUCCESSFUL_DELIVERIES |
| Fixture, 09/01/2030 10:30 UTC | 2 giả | 0 | 2 | 0 | WAITING_24H |
| Fixture, 10/01/2030 12:00 UTC | 4 giả | 3 | 1 | 1 | PARTIALLY_MATURED |
| Fixture, 11/01/2030 13:00 UTC | 5 giả | 5 | 0 | 2 | MATURED_DESCRIPTIVE_ONLY |

DB demo có một intervention `replan`, variant ai, delivery SIMULATED, cùng completion do adapter demo xác nhận. Vì chưa gửi thành công thật nên cohort=0, rate=null; không được biến SIMULATED thành SENT để có số liệu. [Results](results/localhost-demo/results.json) và [input tối thiểu từ DB demo](results/localhost-demo/source-dataset.json) cho phép đối chiếu/tái lập.

Fixture partial có check-in sớm nhưng vẫn pending, check-in quá 24h bị loại, replay không tạo phản hồi mới và một SENT tương lai bị loại tại cutoff. [Waiting](results/boundary-waiting/report.md), [partial](results/boundary-partial/report.md), [matured](results/boundary-matured/report.md) ghi số đếm/tỷ lệ theo variant. Các con số đó là kết quả code trên input giả, không đo tác động AI.

Chưa có mẫu thật, human rubric hoặc 24h quan sát thông báo production. Chưa ước lượng nhân quả; parity ID không phải phân nhóm ngẫu nhiên. Cần SE/PO nối acknowledgement gửi thành công, AI Vision cung cấp completion được xác nhận và chờ đủ window trước khi phân tích pilot.

[Runner/cách chạy](README.md) · [Contract](../../docs/contracts/plan-coach-se-po.md) · [Bàn giao cuối](../../docs/plan-coach-handoff.md)
