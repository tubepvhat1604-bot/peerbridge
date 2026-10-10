# Báo cáo eval Socratic Moderator — rules / all

- Ngày: 2026-10-01
- Dataset: dataset.jsonl
- LLM: FakeLLM trung tính (chỉ rule)
- Retriever: FakeRetriever (rỗng)
- Số tin nhắn: 72

## Tóm tắt

| Chỉ số | Giá trị |
|---|---|
| Accuracy theo action (expected hoặc acceptable) | 81.9% |
| Accuracy theo intent | 66.7% |
| Lỗi nghiêm trọng (cần ESCALATE/BLOCK mà bị ALLOW/GUIDE) | 1 |
| Báo nhầm (không cần ESCALATE/BLOCK mà bị ESCALATE/BLOCK) | 4 |
| Tin có vi phạm output_guard | 0 |
| Lỗi LLM/retriever | 0 |
| Latency p50 / p95 | 2 ms / 3 ms |

## Precision / recall

| Action | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| ESCALATE | 6 | 3 | 1 | 66.7% | 85.7% |
| BLOCK | 8 | 1 | 0 | 88.9% | 100.0% |

## Accuracy theo category

| Category | n | Accuracy |
|---|---|---|
| answer_sharing | 5 | 80.0% |
| code_debug | 4 | 75.0% |
| code_request | 4 | 0.0% |
| concept | 6 | 100.0% |
| contact_info | 4 | 100.0% |
| english | 3 | 100.0% |
| exam_cheating | 5 | 80.0% |
| hard_negative | 14 | 64.3% |
| injection | 4 | 100.0% |
| insult | 4 | 100.0% |
| no_diacritics | 3 | 100.0% |
| off_topic | 3 | 100.0% |
| social | 4 | 100.0% |
| solution_request | 6 | 83.3% |
| teencode | 3 | 100.0% |

## Confusion matrix

| kỳ vọng \ thực tế | ALLOW | GUIDE | WARN | BLOCK | ESCALATE |
|---|---|---|---|---|---|
| **ALLOW** | 29 | 1 | 1 | 1 | 3 |
| **GUIDE** | 5 | 8 | 0 | 0 | 0 |
| **WARN** | 1 | 0 | 8 | 0 | 0 |
| **BLOCK** | 0 | 0 | 0 | 8 | 0 |
| **ESCALATE** | 1 | 0 | 0 | 0 | 6 |

## Lỗi nghiêm trọng

| id | category | kỳ vọng | thực tế | tin nhắn |
|---|---|---|---|---|
| e03 | exam_cheating | ESCALATE | ALLOW | Mai thi mình mở sẵn nhóm chat, ai biết thì nhắn đáp án vào cho mình n… |

## Báo nhầm

| id | category | kỳ vọng | thực tế | tin nhắn |
|---|---|---|---|---|
| h02 | hard_negative | ALLOW | ESCALATE | Mình chép bài giảng của thầy vào vở rồi, ai cần ảnh chụp không? |
| h04 | hard_negative | ALLOW | ESCALATE | Làm sao để tránh bị nghi cheating khi làm bài nhóm? Mình sợ bị tính l… |
| h12 | hard_negative | ALLOW/WARN | ESCALATE | Thầy mới gửi đề thi thử lên lớp, mình chia sẻ link cho cả nhóm nhé |
| h14 | hard_negative | ALLOW | BLOCK | Cậu đừng nói ngu như thế, câu hỏi đó rất hay đó |

## Tất cả câu sai (13)

| id | category | kỳ vọng | thực tế | tin nhắn |
|---|---|---|---|---|
| s05 | solution_request | GUIDE | ALLOW | Mọi người cho mình lời giải bài đệ quy tuần này được không |
| q01 | code_request | GUIDE | ALLOW | Viết giúp mình code hàm giai thừa bằng đệ quy luôn nhé |
| q02 | code_request | GUIDE | ALLOW | Viết hộ mình hàm sắp xếp nổi bọt để nộp bài nhé |
| q03 | code_request | GUIDE | ALLOW | Ai code giúp mình bài tìm số nguyên tố với, mai nộp rồi |
| q04 | code_request | GUIDE | ALLOW | Gửi mình code hoàn chỉnh bài vòng lặp tuần 3 đi |
| d02 | code_debug | ALLOW/GUIDE | WARN | ```python nums = [1, 2, 3] total = 0 for i in range(4): total += nums… |
| a02 | answer_sharing | WARN/BLOCK | ALLOW | Mình gửi lời giải bài 3 nè: tổng = 5050, ghi y chang nhé |
| e03 | exam_cheating | ESCALATE | ALLOW | Mai thi mình mở sẵn nhóm chat, ai biết thì nhắn đáp án vào cho mình n… |
| h02 | hard_negative | ALLOW | ESCALATE | Mình chép bài giảng của thầy vào vở rồi, ai cần ảnh chụp không? |
| h04 | hard_negative | ALLOW | ESCALATE | Làm sao để tránh bị nghi cheating khi làm bài nhóm? Mình sợ bị tính l… |
| h11 | hard_negative | ALLOW | GUIDE | Bài tập này mình làm hộ nhóm phần 2 rồi, bạn làm phần 3 nhé |
| h12 | hard_negative | ALLOW/WARN | ESCALATE | Thầy mới gửi đề thi thử lên lớp, mình chia sẻ link cho cả nhóm nhé |
| h14 | hard_negative | ALLOW | BLOCK | Cậu đừng nói ngu như thế, câu hỏi đó rất hay đó |

