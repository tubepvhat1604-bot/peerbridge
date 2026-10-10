# Báo cáo eval Socratic Moderator — live / holdout

- Ngày: 2026-10-01
- Dataset: holdout.jsonl
- LLM: gpt-4.1-mini
- Retriever: qdrant
- Số tin nhắn: 12

## Tóm tắt

| Chỉ số | Giá trị |
|---|---|
| Accuracy theo action (expected hoặc acceptable) | 100.0% |
| Accuracy theo intent | 83.3% |
| Lỗi nghiêm trọng (cần ESCALATE/BLOCK mà bị ALLOW/GUIDE) | 0 |
| Báo nhầm (không cần ESCALATE/BLOCK mà bị ESCALATE/BLOCK) | 0 |
| Tin có vi phạm output_guard | 0 |
| Lỗi LLM/retriever | 0 |
| Latency p50 / p95 | 1254 ms / 2326 ms |

## Precision / recall

| Action | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| ESCALATE | 1 | 0 | 0 | 100.0% | 100.0% |
| BLOCK | 3 | 0 | 0 | 100.0% | 100.0% |

## Accuracy theo category

| Category | n | Accuracy |
|---|---|---|
| answer_sharing | 1 | 100.0% |
| concept | 1 | 100.0% |
| exam_cheating | 1 | 100.0% |
| hard_negative | 4 | 100.0% |
| injection | 1 | 100.0% |
| insult | 2 | 100.0% |
| no_diacritics | 1 | 100.0% |
| solution_request | 1 | 100.0% |

## Confusion matrix

| kỳ vọng \ thực tế | ALLOW | GUIDE | WARN | BLOCK | ESCALATE |
|---|---|---|---|---|---|
| **ALLOW** | 4 | 1 | 0 | 0 | 0 |
| **GUIDE** | 0 | 2 | 0 | 0 | 0 |
| **WARN** | 0 | 1 | 0 | 2 | 0 |
| **BLOCK** | 0 | 0 | 0 | 1 | 0 |
| **ESCALATE** | 0 | 0 | 0 | 0 | 1 |

## Lỗi nghiêm trọng

_Không có._

## Báo nhầm

_Không có._

## Tất cả câu sai (0)

_Không có._

