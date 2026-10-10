# Báo cáo eval Socratic Moderator — live / dev

- Ngày: 2026-10-01
- Dataset: dataset.jsonl
- LLM: gpt-4.1-mini
- Retriever: qdrant
- Số tin nhắn: 39

## Tóm tắt

| Chỉ số | Giá trị |
|---|---|
| Accuracy theo action (expected hoặc acceptable) | 100.0% |
| Accuracy theo intent | 92.3% |
| Lỗi nghiêm trọng (cần ESCALATE/BLOCK mà bị ALLOW/GUIDE) | 0 |
| Báo nhầm (không cần ESCALATE/BLOCK mà bị ESCALATE/BLOCK) | 0 |
| Tin có vi phạm output_guard | 0 |
| Lỗi LLM/retriever | 0 |
| Latency p50 / p95 | 1348 ms / 4392 ms |

## Precision / recall

| Action | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| ESCALATE | 5 | 0 | 0 | 100.0% | 100.0% |
| BLOCK | 8 | 0 | 0 | 100.0% | 100.0% |

## Accuracy theo category

| Category | n | Accuracy |
|---|---|---|
| answer_sharing | 3 | 100.0% |
| code_debug | 2 | 100.0% |
| code_request | 2 | 100.0% |
| concept | 3 | 100.0% |
| contact_info | 2 | 100.0% |
| english | 2 | 100.0% |
| exam_cheating | 3 | 100.0% |
| hard_negative | 7 | 100.0% |
| injection | 2 | 100.0% |
| insult | 2 | 100.0% |
| no_diacritics | 2 | 100.0% |
| off_topic | 2 | 100.0% |
| social | 2 | 100.0% |
| solution_request | 3 | 100.0% |
| teencode | 2 | 100.0% |

## Confusion matrix

| kỳ vọng \ thực tế | ALLOW | GUIDE | WARN | BLOCK | ESCALATE |
|---|---|---|---|---|---|
| **ALLOW** | 16 | 1 | 0 | 0 | 0 |
| **GUIDE** | 0 | 7 | 0 | 0 | 0 |
| **WARN** | 0 | 0 | 2 | 3 | 0 |
| **BLOCK** | 0 | 0 | 0 | 5 | 0 |
| **ESCALATE** | 0 | 0 | 0 | 0 | 5 |

## Lỗi nghiêm trọng

_Không có._

## Báo nhầm

_Không có._

## Tất cả câu sai (0)

_Không có._

