# Eval chấm phiên học: rules

- Ngày: 2026-10-09
- Bộ dữ liệu: backend/app/session_review/eval_dataset.jsonl (10 phiên)

| Chỉ số | Giá trị |
|---|---|
| Độ đúng phát hiện lộ đáp án | 70% |
| Precision lộ đáp án | 100% |
| Recall lộ đáp án | 25% |
| Độ đúng nhãn Socratic (cao/thấp) | 100% |

| Phiên | Lộ (kỳ vọng) | Lộ (chấm) | Socratic (kỳ vọng) | Socratic (chấm) | Điểm |
|---|---|---|---|---|---|
| s01-socratic-sql | False | False | high | high | 1.0 |
| s02-leak-code | True | False | low | low | 0.0 |
| s03-leak-number | True | False | low | low | 0.0 |
| s04-small-talk | False | False | none | none | None |
| s05-concept-explain | False | False | high | high | 1.0 |
| s06-lecture-no-question | False | False | low | low | 0.0 |
| s07-exam-share | True | True | low | low | 0.0 |
| s08-mixed-recovered | False | False | high | high | 1.0 |
| s09-full-solution-prose | True | False | low | low | 0.0 |
| s10-learner-led | False | False | high | high | 1.0 |
