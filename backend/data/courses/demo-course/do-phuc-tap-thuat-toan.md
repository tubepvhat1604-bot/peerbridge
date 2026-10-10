# Độ phức tạp thuật toán

Độ phức tạp thuật toán mô tả thời gian chạy hoặc bộ nhớ cần dùng theo kích thước đầu vào n, thường biểu diễn bằng ký hiệu Big-O. Big-O chỉ quan tâm tốc độ tăng khi n lớn, bỏ qua hằng số và các số hạng nhỏ.

Các mức thường gặp, từ nhanh đến chậm: O(1) hằng số, O(log n) logarit như tìm kiếm nhị phân, O(n) tuyến tính như duyệt mảng, O(n log n) như sắp xếp trộn, O(n^2) như hai vòng lặp lồng nhau, O(2^n) như đệ quy vét cạn.

Để ước lượng, đếm số lần thao tác chính được thực hiện: vòng lặp đơn qua n phần tử là O(n); hai vòng lặp lồng nhau cùng chạy n lần là O(n^2). Với đệ quy, hãy viết công thức truy hồi rồi giải.

Chọn thuật toán phù hợp phụ thuộc vào kích thước dữ liệu: với n nhỏ, thuật toán đơn giản O(n^2) vẫn chấp nhận được; với n rất lớn cần O(n log n) trở xuống.
