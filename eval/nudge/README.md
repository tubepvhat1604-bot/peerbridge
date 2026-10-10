# Eval Nudge

`run.py` gọi bộ phân tích `reminder_report` của Plan/Coach. Chỉ đọc intervention/delivery/completion, không gửi thông báo, sửa DB, tính lại pacing/gap hoặc đọc chat/ảnh. Đường DB được mở `mode=ro` và `query_only`; file phải tồn tại. Fixture dựng DB trong RAM, không tạo endpoint check-in.

Từ root:

```powershell
$nudgeEvalRun = 'eval/nudge/runs/' + [guid]::NewGuid().ToString('N')
& '.\.venv\Scripts\python.exe' eval/nudge/run.py --dataset eval/nudge/dataset.json --output "$nudgeEvalRun/boundary-partial"
& '.\.venv\Scripts\python.exe' eval/nudge/run.py --dataset eval/nudge/dataset.json --as-of 2030-01-09T10:30:00+00:00 --output "$nudgeEvalRun/boundary-waiting"
& '.\.venv\Scripts\python.exe' eval/nudge/run.py --dataset eval/nudge/dataset.json --as-of 2030-01-11T13:00:00+00:00 --output "$nudgeEvalRun/boundary-matured"
```

Output phải là thư mục chưa tồn tại; runner từ chối ghi đè cả thư mục rỗng. Mỗi lần nghiệm thu dùng UUID mới, giữ nguyên tất cả report/evidence cũ. DB read-only dùng một transaction snapshot cho báo cáo và input export; lần SENT đầu tiên được chọn theo thời gian UTC, không theo thứ tự chuỗi ISO khác offset.

`dataset.json` là fixture synthetic có SENT giả, replay, phản hồi quá hạn, phản hồi sớm, delivery đang chờ/lỗi và timestamp tương lai. Các tỷ lệ trong những thư mục boundary chỉ kiểm tra code, không phải pilot. Dataset không ghi điểm rubric.

Đã phân tích DB tạm của smoke localhost bằng `--database ... --simulation`: [kết quả demo](results/localhost-demo/results.json), [input đã xuất](results/localhost-demo/source-dataset.json). Tái lập từ input được xuất:

```powershell
$nudgeReplayRun = '.tmp/nudge-demo-replay-' + [guid]::NewGuid().ToString('N')
& '.\.venv\Scripts\python.exe' eval/nudge/run.py --dataset eval/nudge/results/localhost-demo/source-dataset.json --output $nudgeReplayRun
```

Phân tích một DB được chỉ định rõ (đổi đường dẫn và cutoff thật):

```powershell
$nudgeDbRun = '.tmp/nudge-db-analysis-' + [guid]::NewGuid().ToString('N')
& '.\.venv\Scripts\python.exe' eval/nudge/run.py --database 'D:/Vin/P-005/.tmp/your-isolated-demo/demo.db' --as-of 2030-01-10T08:00:00+07:00 --simulation --output $nudgeDbRun
```

`--as-of` bắt buộc với DB và phải có offset. `--simulation` đánh dấu dữ liệu demo, đồng thời xuất input tối thiểu không có nội dung tin/chat/key. Nếu dùng DB khác, nguồn vẫn `production_origin_verified=false`; bỏ flag không tự biến dữ liệu thành production đã kiểm chứng.

| Trạng thái báo cáo | Ý nghĩa |
| --- | --- |
| NO_SUCCESSFUL_DELIVERIES | Không có acknowledgement SENT tại hoặc trước cutoff; rate=null |
| WAITING_24H | Có SENT nhưng tất cả chưa đủ 24h; rate=null |
| PARTIALLY_MATURED | Có cả mẫu đủ 24h và mẫu pending; rate chỉ dùng mẫu đủ 24h |
| MATURED_DESCRIPTIVE_ONLY | Mọi mẫu SENT trong cutoff đã đủ 24h; vẫn chỉ mô tả |

Window [sent_at, sent_at+24h]; dưới 24h luôn pending kể cả check-in sớm. Chỉ lần completion đầu tiên của cùng người/cặp, không tính replay. Chỉ acknowledgement SENT vào cohort; delivery PENDING khác với observation pending. `current_delivery_status_counts` là trạng thái đang lưu của intervention đã tạo trước cutoff, không tái dựng lịch sử status trong quá khứ. `ran_at` là thời gian chạy thật, `as_of` là cutoff dữ liệu.

[Báo cáo tổng hợp](report.md) · [Contract SE/PO](../../docs/contracts/plan-coach-se-po.md). Chưa có thông báo/pilot thật để kết luận hiệu quả hoặc nhân quả.
