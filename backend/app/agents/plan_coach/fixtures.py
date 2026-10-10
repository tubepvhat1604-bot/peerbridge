"""Synthetic personas: never used as production profiles, metrics or pilot evidence."""

from datetime import datetime

from .contract import Availability, Concept, Member, PlannerInput


def demo_catalog():
    return [
        Concept(id="english.introduce", track="english", action="Tập giới thiệu bản thân bằng tiếng Anh trong 2 phút", expected_output="Ghi âm 2 phút và ghi lại 5 từ mới", est_minutes=30),
        Concept(id="english.daily", track="english", prerequisites=["english.introduce"], action="Luyện 10 câu hỏi về sinh hoạt hằng ngày với bạn", expected_output="Trả lời 10 câu hỏi và ghi lại 3 cách diễn đạt mới", est_minutes=45),
        Concept(id="english.conversation", track="english", prerequisites=["english.daily"], action="Thực hành hội thoại 5 phút tại quán cà phê", expected_output="Hội thoại 5 phút và phản hồi từ bạn đồng hành", est_minutes=50),
        Concept(
            id="sql.select",
            track="sql",
            action="Viết 5 câu SELECT trên bảng students",
            expected_output="File chứa 5 câu truy vấn và kết quả",
            est_minutes=30,
        ),
        Concept(
            id="sql.where",
            track="sql",
            prerequisites=["sql.select"],
            action="Viết 5 câu truy vấn lọc bằng WHERE",
            expected_output="5 truy vấn và giải thích điều kiện lọc",
            est_minutes=45,
        ),
        Concept(
            id="sql.join",
            track="sql",
            prerequisites=["sql.where"],
            action="Ghép hai bảng bằng 3 câu INNER JOIN",
            expected_output="3 truy vấn JOIN và bảng kết quả",
            est_minutes=60,
        ),
        Concept(
            id="python.variables",
            track="python",
            action="Viết chương trình nhập tên và tính tuổi",
            expected_output="File Python và 3 lần chạy thử",
            est_minutes=30,
        ),
        Concept(
            id="python.conditions",
            track="python",
            prerequisites=["python.variables"],
            action="Viết chương trình phân loại điểm bằng if/else",
            expected_output="File Python với 5 trường hợp kiểm thử",
            est_minutes=45,
        ),
        Concept(
            id="python.loops",
            track="python",
            prerequisites=["python.conditions"],
            action="Dùng vòng lặp tính tổng và lọc số chẵn",
            expected_output="Hai hàm Python và 5 ví dụ chạy",
            est_minutes=60,
        ),
    ]


def synthetic_context(case="normal", index=0):
    start = datetime.fromisoformat("2030-01-07T08:00:00+07:00")
    windows = [
        Availability(id=f"slot-{day}", day_of_week=day, start_time="19:00", end_time="20:30") for day in range(5)
    ]
    left = Member(
        user_id=101 + index * 2,
        goal="Học truy vấn SQL cơ bản",
        concept_ids=["sql.join"],
        committed_minutes_per_week=180,
        availability=windows,
        known_concept_ids=["python.variables", "python.conditions", "python.loops"],
        can_help_concept_ids=["python.loops"],
    )
    right = Member(
        user_id=102 + index * 2,
        goal="Học Python cơ bản",
        concept_ids=["python.loops"],
        committed_minutes_per_week=180,
        availability=windows,
        known_concept_ids=["sql.select", "sql.where", "sql.join"],
        can_help_concept_ids=["sql.join"],
    )
    concepts = demo_catalog()
    if case == "little_time":
        left.committed_minutes_per_week = 30
    elif case == "no_shared_time":
        right.availability = [
            w.model_copy(update={"start_time": w.start_time.replace(hour=9), "end_time": w.end_time.replace(hour=10)})
            for w in windows
        ]
    elif case == "impossible_deadline":
        left.deadline = datetime.fromisoformat("2030-01-07T19:40:00+07:00")
    elif case == "missing_prerequisite":
        concepts[1].prerequisites = ["sql.missing"]
    elif case == "late":
        left.availability = windows[:2]
    return PlannerInput(
        pair_id=1 + index,
        members=[left, right],
        concepts=concepts,
        planning_start=start,
        catalog_source="synthetic_demo",
    )
