# Eval Plan — kết quả chạy thực tế trên persona synthetic

20 persona; development 14, holdout 6. Cùng dataset chạy ở hai mode, không cộng thành hai nhóm người khác nhau.

Prompt `plan-coach-planner-v1`, SHA-256 `92efe6e97d1111c4c2f0adead30b369e3d89051baba2fd612fbd450ca9999f7f`. Lượt chạy 2026-10-06T08:15:07.862170+00:00 → 2026-10-06T08:15:23.739896+00:00.

| Mode | Cặp nhận/tổng | Personal plan hard-pass | Personal plan partial | Lỗi sinh đầu/ca sinh | Repair thành công |
| --- | --- | --- | --- | --- | --- |
| template | 9/10 | 18 | 6/18 | 0/9 | 0 |
| fake | 9/10 | 18 | 6/18 | 9/9 | 9 |

Các output được chấp nhận đã được runner summary kiểm tra lại bằng validator của app. Xem từng lỗi/trace/split trong results/<mode>-<split>/results.json. Dataset thiếu prerequisite bị từ chối trước generator; không tính là lỗi sinh model.

FakeLLM cố ý trả tasks rỗng ở lần đầu để kiểm tra repair. Đây không phải tỷ lệ lỗi của LLM thật. Plan partial chỉ đáp ứng một phần goal.

Chưa chạy AI/judge thật hoặc chấm tay: cả hai count=0, trung bình=null, mục tiêu ≥4/5 chưa xác nhận. CSV trống của mỗi run dành cho người chấm; hướng dẫn [rubric](../../docs/plan-eval-rubric.md). Không dùng kết quả holdout để sửa prompt trong lượt bàn giao này.

[Hướng dẫn chạy](README.md) · [Kiểm thử và thao tác app](../../docs/plan-coach-testing.md)
