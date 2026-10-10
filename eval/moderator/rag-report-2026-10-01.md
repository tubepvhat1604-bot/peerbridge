# Báo cáo RAG eval — intfloat/multilingual-e5-large @ http://localhost:6333

- Ngày: 2026-10-01
- k = 4; 15 câu liên quan, 5 câu không liên quan

| Chỉ số | Giá trị |
|---|---|
| hit@1 | 93.3% |
| hit@4 | 100.0% |
| Score câu liên quan (chunk đúng nguồn) | min 0.771 | p25 0.835 | median 0.858 | p75 0.873 | max 0.896 |
| Score top-1 câu không liên quan | min 0.726 | p25 0.746 | median 0.748 | p75 0.755 | max 0.767 |
| **RAG_MIN_SCORE đề xuất** | **0.769** |
| Với RAG_MIN_SCORE hiện tại (0.82) | 12/15 câu liên quan qua ngưỡng, 0/5 câu không liên quan lọt qua |

## Chi tiết

| id | nguồn kỳ vọng | top sources | top-1 score | score nguồn đúng |
|---|---|---|---|---|
| r01 | de-quy.md | de-quy.md, vong-lap.md, do-phuc-tap-thuat-toan.md | 0.870 | 0.870 |
| r02 | de-quy.md | de-quy.md, do-phuc-tap-thuat-toan.md, vong-lap.md | 0.782 | 0.782 |
| r03 | de-quy.md | de-quy.md, do-phuc-tap-thuat-toan.md, vong-lap.md | 0.881 | 0.881 |
| r04 | de-quy.md | de-quy.md, do-phuc-tap-thuat-toan.md, vong-lap.md | 0.889 | 0.889 |
| r05 | de-quy.md | de-quy.md, do-phuc-tap-thuat-toan.md, vong-lap.md | 0.858 | 0.858 |
| r06 | vong-lap.md | vong-lap.md, de-quy.md, do-phuc-tap-thuat-toan.md | 0.873 | 0.873 |
| r07 | vong-lap.md | vong-lap.md, de-quy.md, do-phuc-tap-thuat-toan.md | 0.844 | 0.844 |
| r08 | vong-lap.md | de-quy.md, vong-lap.md, do-phuc-tap-thuat-toan.md | 0.780 | 0.771 |
| r09 | vong-lap.md | vong-lap.md, de-quy.md, do-phuc-tap-thuat-toan.md | 0.839 | 0.839 |
| r10 | vong-lap.md | vong-lap.md, de-quy.md, do-phuc-tap-thuat-toan.md | 0.896 | 0.896 |
| r11 | do-phuc-tap-thuat-toan.md | do-phuc-tap-thuat-toan.md, de-quy.md, vong-lap.md | 0.820 | 0.820 |
| r12 | do-phuc-tap-thuat-toan.md | do-phuc-tap-thuat-toan.md, de-quy.md, vong-lap.md | 0.864 | 0.864 |
| r13 | do-phuc-tap-thuat-toan.md | do-phuc-tap-thuat-toan.md, vong-lap.md, de-quy.md | 0.857 | 0.857 |
| r14 | do-phuc-tap-thuat-toan.md | do-phuc-tap-thuat-toan.md, de-quy.md, vong-lap.md | 0.835 | 0.835 |
| r15 | do-phuc-tap-thuat-toan.md | do-phuc-tap-thuat-toan.md, vong-lap.md, de-quy.md | 0.866 | 0.866 |
| x01 | (không liên quan) | vong-lap.md, de-quy.md, do-phuc-tap-thuat-toan.md | 0.767 | — |
| x02 | (không liên quan) | do-phuc-tap-thuat-toan.md, de-quy.md, vong-lap.md | 0.748 | — |
| x03 | (không liên quan) | vong-lap.md, do-phuc-tap-thuat-toan.md, de-quy.md | 0.746 | — |
| x04 | (không liên quan) | vong-lap.md, de-quy.md, do-phuc-tap-thuat-toan.md | 0.726 | — |
| x05 | (không liên quan) | de-quy.md, do-phuc-tap-thuat-toan.md, vong-lap.md | 0.755 | — |
