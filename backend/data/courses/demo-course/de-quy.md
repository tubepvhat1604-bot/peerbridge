# Đệ quy

Đệ quy là kỹ thuật trong đó một hàm tự gọi lại chính nó để giải quyết bài toán nhỏ hơn cùng dạng. Mỗi hàm đệ quy cần có hai phần: trường hợp cơ sở (điều kiện dừng) và bước đệ quy (gọi lại hàm với đầu vào nhỏ hơn).

Ví dụ kinh điển là tính giai thừa: n! = n * (n - 1)!, với trường hợp cơ sở 0! = 1. Nếu thiếu trường hợp cơ sở, hàm sẽ gọi lại vô hạn và gây tràn ngăn xếp (stack overflow).

Khi gặp lỗi đệ quy, hãy tự hỏi: đầu vào có thực sự nhỏ đi sau mỗi lần gọi không? Trường hợp cơ sở có bao phủ mọi đầu vào nhỏ nhất không? Vẽ cây gọi hàm cho một đầu vào nhỏ thường giúp nhìn ra lỗi.

Nhiều bài toán đệ quy có thể viết lại bằng vòng lặp kết hợp cấu trúc ngăn xếp. Đệ quy cho mã ngắn gọn, nhưng tốn bộ nhớ ngăn xếp theo độ sâu gọi.
