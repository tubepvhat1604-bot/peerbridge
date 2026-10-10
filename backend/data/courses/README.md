# Tài liệu môn học cho RAG phòng học

Moderator phòng học tìm đoạn liên quan trong `data/courses/<course_id>/*.md` bằng BM25, rồi gợi ý kèm nguồn
"(Xem bài <tên file>, slide N)". Không cần vector DB hay embedding.

- `demo-course/`: 3 bài ngắn tự viết (vòng lặp, đệ quy, độ phức tạp thuật toán) để chạy thử.
- `aicb/`: bản chạy thật dùng slide bài giảng ngày 1–15, Phase 1 AI Thực Chiến. Thư mục này **không kèm trong repo** vì nhóm không có quyền chia sẻ slide.

## Dùng tài liệu của bạn

1. Đặt slide (`.pdf`, hoặc `.txt` đã tách chữ) vào một thư mục. Đặt tên file theo nội dung bài, ví dụ `RAG Pipeline.pdf`,
   vì tên file chính là tên bài khi AI trích nguồn.
2. Chuyển thành markdown, mỗi slide một khối `<!-- page:N -->`:

   ```bash
   cd backend
   python scripts/build_slide_corpus.py <thư mục slide> data/courses/<course_id>
   ```

3. Đặt `RETRIEVER_PROVIDER=local` và `RAG_DEFAULT_COURSE_ID=<course_id>` (trong `backend/.env` hoặc trên Render).

File markdown viết tay cũng dùng được: không có khối `<!-- page:N -->` thì nội dung được chia theo đoạn (cách nhau một dòng trống)
thành các đoạn ngắn để tìm kiếm.
