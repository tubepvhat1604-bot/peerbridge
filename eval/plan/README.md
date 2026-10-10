# Eval Plan

Runner tại đây tái sử dụng `backend/app/agents/plan_coach/eval.py`, scheduler và validator của app. Không gọi module Moderator. Các mode được hỗ trợ là template và fake; chưa có runner eval live-provider ở entry point này.

`dataset.json` chứa 10 cặp/20 persona synthetic: 7 development, 3 holdout. Giữ split theo cặp và khóa prompt trước khi chạy holdout. Dataset hiện đã có kết quả đánh giá, không được dùng holdout này chỉnh prompt rồi gọi đó là holdout mới.

Từ root `D:\Vin\P-005`, chạy từng lệnh PowerShell:

```powershell
$planEvalRun = 'eval/plan/runs/' + [guid]::NewGuid().ToString('N')
& '.\.venv\Scripts\python.exe' eval/plan/run.py --mode template --split development --output "$planEvalRun/results/template-development"
& '.\.venv\Scripts\python.exe' eval/plan/run.py --mode fake --split development --output "$planEvalRun/results/fake-development"
& '.\.venv\Scripts\python.exe' eval/plan/run.py --mode template --split holdout --output "$planEvalRun/results/template-holdout"
& '.\.venv\Scripts\python.exe' eval/plan/run.py --mode fake --split holdout --output "$planEvalRun/results/fake-holdout"
& '.\.venv\Scripts\python.exe' eval/plan/run.py --summarize --results-dir "$planEvalRun/results" --output "$planEvalRun/summary"
```

Mỗi run ghi dataset/results và CSV rubric trống; summary ghi summary/report. Runner **từ chối mọi thư mục output đã tồn tại**, kể cả rỗng, và mở file ở chế độ tạo mới độc quyền. Không ghi đè CSV đã chấm hoặc evidence cũ. Nếu không truyền `--output`/`--results-dir`, mỗi lần sinh tự dùng thư mục mới có timestamp/UUID trong `runs/`. Summary bắt buộc chỉ định `--results-dir`, không ngầm dùng kết quả cũ. Các [kết quả bàn giao trước](report.md) được giữ nguyên.

`--write-dataset --dataset <file-mới>` xuất fixture; file đã có bị từ chối, bao gồm dataset đóng băng. Không dùng lại fixture này như một cách tạo holdout mới từ mẫu cũ.

Summary so sánh dataset hash/prompt hash và kiểm tra lại output được nhận bằng validator. Nếu thiếu kết quả split, prompt khác nhau hoặc output vi phạm, runner thất bại thay vì báo hard-pass. `human_rating_count` và `llm_judge_count` của runner offline là 0: runner không đọc hoặc tự điền điểm chất lượng.

FakeLLM cố ý trả batch rỗng lần đầu rồi sửa; thống kê repair không phải tỷ lệ lỗi model thật. [Rubric 1–5 và hướng dẫn chấm tay](../../docs/plan-eval-rubric.md). [Hướng dẫn kiểm app](../../docs/plan-coach-testing.md).
