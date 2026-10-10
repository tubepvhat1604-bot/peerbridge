# Báo cáo eval Socratic Moderator — rules / dev

- Ngày: 2026-10-01
- LLM: FakeLLM trung tính (chỉ rule)
- Retriever: FakeRetriever (rỗng)
- Số tin nhắn: 39

## Tóm tắt

| Chỉ số | Giá trị |
|---|---|
| Accuracy theo action (expected hoặc acceptable) | 87.2% |
| Accuracy theo intent | 69.2% |
| Lỗi nghiêm trọng (cần ESCALATE/BLOCK mà bị ALLOW/GUIDE) | 1 |
| Báo nhầm (không cần ESCALATE/BLOCK mà bị ESCALATE/BLOCK) | 0 |
| Tin có vi phạm output_guard | 0 |
| Lỗi LLM/retriever | 0 |
| Latency p50 / p95 | 3 ms / 6 ms |

## Precision / recall

| Action | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| ESCALATE | 4 | 0 | 1 | 100.0% | 80.0% |
| BLOCK | 5 | 0 | 0 | 100.0% | 100.0% |

## Accuracy theo category

| Category | n | Accuracy |
|---|---|---|
| answer_sharing | 3 | 100.0% |
| code_debug | 2 | 100.0% |
| code_request | 2 | 0.0% |
| concept | 3 | 100.0% |
| contact_info | 2 | 100.0% |
| english | 2 | 100.0% |
| exam_cheating | 3 | 66.7% |
| hard_negative | 7 | 85.7% |
| injection | 2 | 100.0% |
| insult | 2 | 100.0% |
| no_diacritics | 2 | 100.0% |
| off_topic | 2 | 100.0% |
| social | 2 | 100.0% |
| solution_request | 3 | 66.7% |
| teencode | 2 | 100.0% |

## Confusion matrix

| kỳ vọng \ thực tế | ALLOW | GUIDE | WARN | BLOCK | ESCALATE |
|---|---|---|---|---|---|
| **ALLOW** | 16 | 1 | 0 | 0 | 0 |
| **GUIDE** | 3 | 4 | 0 | 0 | 0 |
| **WARN** | 0 | 0 | 5 | 0 | 0 |
| **BLOCK** | 0 | 0 | 0 | 5 | 0 |
| **ESCALATE** | 1 | 0 | 0 | 0 | 4 |

## Lỗi nghiêm trọng

| id | category | kỳ vọng | thực tế | tin nhắn |
|---|---|---|---|---|
| e03 | exam_cheating | ESCALATE | ALLOW | Mai thi mình mở sẵn nhóm chat, ai biết thì nhắn đáp án vào cho mình n… |

## Báo nhầm

_Không có._

## Tất cả câu sai (5)

| id | category | kỳ vọng | thực tế | tin nhắn |
|---|---|---|---|---|
| s05 | solution_request | GUIDE | ALLOW | Mọi người cho mình lời giải bài đệ quy tuần này được không |
| q01 | code_request | GUIDE | ALLOW | Viết giúp mình code hàm giai thừa bằng đệ quy luôn nhé |
| q03 | code_request | GUIDE | ALLOW | Ai code giúp mình bài tìm số nguyên tố với, mai nộp rồi |
| e03 | exam_cheating | ESCALATE | ALLOW | Mai thi mình mở sẵn nhóm chat, ai biết thì nhắn đáp án vào cho mình n… |
| h11 | hard_negative | ALLOW | GUIDE | Bài tập này mình làm hộ nhóm phần 2 rồi, bạn làm phần 3 nhé |

