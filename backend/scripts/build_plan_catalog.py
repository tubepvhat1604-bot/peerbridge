"""Tạo danh mục concept cho Plan (Data 2) từ danh mục chuẩn của Data 1.

Data 2 cần mỗi concept có việc cụ thể (action), đầu ra (expected_output) và thời lượng; Data 1 giữ id, tên,
quan hệ tiên quyết. Chạy lại khi Data 1 đổi danh mục:

    cd backend; ..\\.venv\\Scripts\\python.exe scripts\\build_plan_catalog.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "concepts" / "catalog.json"
TARGET = ROOT / "data" / "concepts" / "plan_catalog.json"

# id: (việc cần làm, đầu ra, phút)
ACTIONS: dict[str, tuple[str, str, int]] = {
    "sql.select_basic": ("Viết 5 câu SELECT lấy các cột khác nhau từ một bảng", "5 truy vấn và kết quả", 30),
    "sql.where": ("Viết 5 truy vấn lọc dòng bằng WHERE với AND, OR, IN, BETWEEN", "5 truy vấn và giải thích điều kiện", 45),
    "sql.order_by": ("Sắp xếp kết quả theo 1 và 2 cột, tăng và giảm dần", "4 truy vấn ORDER BY", 30),
    "sql.distinct": ("Lấy giá trị không trùng bằng DISTINCT trên 3 cột khác nhau", "3 truy vấn và số dòng trả về", 30),
    "sql.limit": ("Lấy top N bằng ORDER BY kết hợp LIMIT", "3 truy vấn top N", 30),
    "sql.aggregates": ("Tính COUNT, SUM, AVG, MIN, MAX trên một bảng bán hàng", "5 truy vấn tổng hợp", 45),
    "sql.group_by": ("Viết 3 truy vấn GROUP BY tính tổng theo nhóm", "3 truy vấn và bảng kết quả", 45),
    "sql.having": ("Lọc nhóm bằng HAVING sau GROUP BY", "3 truy vấn HAVING", 45),
    "sql.join": ("Ghép hai bảng bằng 3 câu INNER JOIN", "3 truy vấn JOIN và kết quả", 60),
    "sql.left_join": ("Viết 3 truy vấn LEFT JOIN, tìm dòng không khớp (NULL)", "3 truy vấn và giải thích dòng NULL", 60),
    "sql.join_keys": ("Xác định khóa nối và quan hệ 1-n, n-n giữa 3 bảng", "Sơ đồ quan hệ và 2 truy vấn", 45),
    "sql.self_join": ("Nối bảng với chính nó, ví dụ nhân viên và quản lý", "2 truy vấn self join", 45),
    "sql.union": ("Gộp kết quả bằng UNION và UNION ALL, so sánh khác biệt", "2 truy vấn và nhận xét", 30),
    "sql.subquery": ("Viết 3 truy vấn con trong WHERE và FROM", "3 truy vấn lồng", 60),
    "sql.correlated_subquery": ("Viết 2 truy vấn con tương quan", "2 truy vấn và giải thích cách chạy", 60),
    "sql.exists": ("Dùng EXISTS và NOT EXISTS để kiểm tra tồn tại", "3 truy vấn EXISTS", 45),
    "sql.cte": ("Viết lại một truy vấn lồng bằng WITH (CTE)", "Truy vấn CTE và bản cũ để so sánh", 45),
    "sql.case": ("Phân loại dữ liệu bằng CASE WHEN", "3 truy vấn CASE", 45),
    "sql.nulls": ("Xử lý giá trị NULL bằng IS NULL và COALESCE", "4 truy vấn với NULL", 30),
    "sql.string_functions": ("Dùng hàm chuỗi: UPPER, SUBSTR, LENGTH, REPLACE", "4 truy vấn xử lý chuỗi", 30),
    "sql.date_functions": ("Lọc và nhóm theo ngày, tháng bằng hàm ngày", "3 truy vấn theo thời gian", 45),
    "sql.casting": ("Đổi kiểu dữ liệu bằng CAST trong 3 tình huống", "3 truy vấn CAST", 30),
    "sql.window_func": ("Tính tổng lũy kế bằng SUM() OVER (PARTITION BY ...)", "2 truy vấn window", 60),
    "sql.ranking": ("Xếp hạng bằng ROW_NUMBER, RANK, DENSE_RANK", "3 truy vấn xếp hạng", 60),
    "sql.window_frames": ("Tính trung bình trượt 3 ngày bằng ROWS BETWEEN", "2 truy vấn window frame", 60),
    "sql.insert": ("Thêm dữ liệu bằng INSERT một dòng và nhiều dòng", "Script INSERT chạy được", 30),
    "sql.update": ("Cập nhật dữ liệu có điều kiện bằng UPDATE", "3 câu UPDATE và kiểm tra lại", 30),
    "sql.delete": ("Xóa dữ liệu có điều kiện, kiểm tra bằng SELECT trước", "2 câu DELETE an toàn", 30),
    "sql.table_constraints": ("Tạo bảng với PRIMARY KEY, FOREIGN KEY, NOT NULL, UNIQUE", "Script CREATE TABLE", 45),
    "sql.query_debugging": ("Sửa 3 truy vấn lỗi: sai JOIN, sai GROUP BY, sai lọc", "3 truy vấn đã sửa và nguyên nhân", 60),
    "py.basic": ("Cài Python, chạy chương trình in lời chào và nhận dữ liệu nhập", "File .py chạy được", 30),
    "py.variables": ("Viết chương trình nhập tên, năm sinh và tính tuổi", "File Python và 3 lần chạy thử", 30),
    "py.types": ("Thử int, float, str, bool và đổi kiểu qua lại", "Ghi chú 5 phép đổi kiểu", 30),
    "py.operators": ("Viết máy tính đơn giản với + - * / // % **", "Chương trình máy tính", 30),
    "py.strings": ("Ghép chuỗi, f-string và định dạng số", "4 ví dụ xử lý chuỗi", 30),
    "py.string_methods": ("Chuẩn hóa họ tên bằng strip, title, split, join", "Hàm chuẩn hóa tên", 45),
    "py.lists": ("Làm 10 bài với list: thêm, xóa, tìm, đếm", "File bài tập list", 45),
    "py.tuples": ("Dùng tuple để trả nhiều giá trị và unpack", "3 ví dụ tuple", 30),
    "py.dictionaries": ("Đếm số lần xuất hiện từ trong câu bằng dict", "Chương trình đếm từ", 45),
    "py.sets": ("Tìm phần tử chung, khác nhau giữa 2 danh sách bằng set", "3 bài với set", 30),
    "py.indexing_slicing": ("Cắt chuỗi và list bằng chỉ số, đảo ngược, lấy bước", "6 ví dụ slicing", 30),
    "py.conditions": ("Phân loại điểm học lực bằng if/elif/else", "Chương trình xếp loại", 30),
    "py.for_loop": ("Dùng for tính tổng, trung bình và lọc số chẵn", "3 bài vòng lặp for", 45),
    "py.while_loop": ("Viết trò đoán số dùng while", "Trò chơi đoán số", 45),
    "py.functions": ("Tách chương trình thành 3 hàm có tên rõ ràng", "File có 3 hàm", 45),
    "py.parameters": ("Viết hàm có tham số mặc định và tham số theo tên", "3 hàm và ví dụ gọi", 45),
    "py.return_values": ("Viết hàm trả kết quả thay vì in ra, rồi dùng kết quả", "3 hàm có return", 30),
    "py.scope": ("Thử biến cục bộ và toàn cục, giải thích lỗi thường gặp", "Ghi chú và 2 ví dụ", 30),
    "py.comprehensions": ("Viết lại 3 vòng for bằng list và dict comprehension", "3 cặp code trước/sau", 45),
    "py.exceptions": ("Bắt lỗi nhập sai bằng try/except", "Chương trình không bị dừng khi nhập sai", 45),
    "py.file_io": ("Đọc file văn bản, đếm dòng và ghi kết quả ra file mới", "Script đọc/ghi file", 45),
    "py.json": ("Đọc và ghi danh sách sinh viên dạng JSON", "File JSON và script", 45),
    "py.modules": ("Tách code thành 2 module và import qua lại", "2 file .py import nhau", 45),
    "py.packages": ("Cài một thư viện bằng pip và dùng thử", "Script dùng thư viện vừa cài", 30),
    "py.venv": ("Tạo môi trường ảo, cài gói và xuất requirements.txt", "requirements.txt", 30),
    "py.debugging": ("Tìm và sửa 3 lỗi trong chương trình bằng print và debugger", "Code đã sửa và nguyên nhân", 45),
    "py.tests": ("Viết 3 test cho một hàm bằng assert hoặc pytest", "File test chạy xanh", 45),
    "py.iterators": ("Dùng enumerate, zip, range trong 3 bài", "3 bài dùng hàm lặp", 30),
    "py.sorting": ("Sắp xếp danh sách sinh viên theo điểm bằng sorted và key", "Chương trình sắp xếp", 30),
    "py.dates": ("Tính số ngày đến hạn nộp bài bằng datetime", "Chương trình đếm ngày", 45),
    # Khóa AICB: mỗi bài slide là một việc, đọc bài rồi làm một sản phẩm nhỏ.
    "ai.llm_foundation": ("Đọc bài Nền tảng AI và LLM, tự giải thích token, context window và temperature bằng ví dụ của mình", "Ghi chú 1 trang và 3 câu hỏi còn vướng", 45),
    "ai.business_problem": ("Đọc bài Xác định bài toán kinh doanh cho AI, chọn một bài toán thật và xếp mức tự động hóa phù hợp", "Phiếu mô tả bài toán và mức tự động hóa", 45),
    "ai.react_agent": ("Đọc bài Từ Chatbot đến Agent, vẽ vòng Thought - Action - Observation cho một agent đơn giản", "Sơ đồ vòng ReAct và 1 ví dụ chạy tay", 60),
    "ai.prompt_tool_calling": ("Đọc bài Prompt Engineering và Tool Calling, viết system prompt theo Role / Task / Context / Format và khai báo một tool schema", "System prompt và tool schema JSON", 60),
    "ai.harness": ("Đọc bài Context · Loop · Harness Engineering, liệt kê context, vòng lặp và harness của một agent bạn đã dùng", "Bảng context, vòng lặp, harness của agent", 45),
    "ai.product_thinking": ("Đọc bài Tư duy sản phẩm AI, viết PRD 1 trang cho một tính năng AI: người dùng, vấn đề, tiêu chí thành công", "PRD 1 trang", 60),
    "ai.product_management": ("Đọc bài Quản lý sản phẩm và dự án AI, lập milestone và danh sách rủi ro cho dự án AI của nhóm", "Bảng milestone và rủi ro", 45),
    "ai.data_foundations": ("Đọc bài Data Foundations, chia một tài liệu thành chunk theo 2 cách và so sánh kết quả tìm kiếm", "Bảng so sánh 2 cách chunking", 60),
    "ai.rag_pipeline": ("Đọc bài RAG Pipeline, vẽ luồng truy xuất - sinh câu trả lời và viết prompt bắt AI trích nguồn", "Sơ đồ RAG và prompt có trích nguồn", 60),
    "ai.multi_agent": ("Đọc bài Multi-Agent, thiết kế 2 agent phối hợp bằng LangGraph và ghi rõ agent nào làm gì", "Sơ đồ graph 2 agent", 60),
    "ai.data_pipeline": ("Đọc bài Data Pipeline, liệt kê các điểm pipeline nạp tài liệu có thể hỏng và cách phát hiện sớm", "Checklist kiểm tra pipeline", 45),
    "ai.guardrails": ("Đọc bài Guardrails, thêm guardrail đầu vào, đầu ra và điểm cần người duyệt cho một agent", "Bảng guardrail và điểm HITL", 45),
    "ai.deployment": ("Đọc bài Deployment, đưa một agent mẫu lên cloud và ghi lại từng bước, biến môi trường cần có", "URL chạy được và ghi chú các bước", 60),
    "ai.monitoring": ("Đọc bài Monitoring, thêm log và 3 chỉ số theo dõi cho agent đã deploy", "Log mẫu và 3 chỉ số theo dõi", 45),
    "ai.evaluation": ("Đọc bài AI Evaluation, dựng bộ 10 câu hỏi đánh giá và chấm agent theo rubric", "Bộ test 10 câu và bảng điểm", 60),
}


def build() -> dict:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    concepts = []
    for c in source["concepts"]:
        action, output, minutes = ACTIONS.get(
            c["id"], (f"Luyện tập {c['name']}: làm 3 bài nhỏ", "3 bài tập và ghi chú", 45)
        )
        concepts.append({
            "id": c["id"],
            "track": c["domain"],
            "prerequisites": c.get("prerequisites", []),
            "action": action,
            "expected_output": output,
            "est_minutes": minutes,
            "resource_ids": [],
        })
    return {"catalog_version": source["catalog_version"], "concepts": concepts, "resources": {}}


if __name__ == "__main__":
    TARGET.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {TARGET}")
