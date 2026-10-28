import datetime

from sqlalchemy import event

from app.models import Department, HospitalCampus, OperationLog
from app.routers.admin import get_department_list
from app.routers.system import get_log_stats


def count_selects(db, operation):
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        result = operation()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return result, statements


def test_department_pages_keep_director_and_campus_with_bounded_queries(seed_data, db_session):
    now = datetime.datetime.now()
    campus = HospitalCampus(code="PERF-CAMPUS", name="性能院区", create_time=now, update_time=now)
    db_session.add(campus)
    db_session.flush()
    campus_id = campus.campus_id
    director_id = seed_data["doctor"].doctor_id
    director_name = seed_data["doctor"].name
    db_session.add_all([
        Department(name=f"性能科室{index}", campus_id=campus_id, director=director_id if index % 2 else None)
        for index in range(25)
    ])
    db_session.commit()
    db_session.expunge_all()

    result, statements = count_selects(db_session, lambda: get_department_list(
        campus_id=campus_id, page=1, page_size=20, current_user=None, db=db_session,
    ))

    assert result["total"] == 25
    assert len(result["data"]) == 20
    assert len(statements) == 3
    assert {row["campus_name"] for row in result["data"]} == {"性能院区"}
    assert {row["director"] for row in result["data"]} == {"", director_name}

    filtered, _ = count_selects(db_session, lambda: get_department_list(
        keyword=director_name, campus_id=campus_id, page=2, page_size=20, current_user=None, db=db_session,
    ))
    assert filtered["total"] == 25
    assert filtered["data"] and all(row["director"] == director_name for row in filtered["data"])


def test_empty_department_page_skips_director_lookup(db_session):
    result, statements = count_selects(db_session, lambda: get_department_list(
        campus_id=-1, page=1, page_size=20, current_user=None, db=db_session,
    ))
    assert result["data"] == []
    assert result["total"] == 0
    assert len(statements) == 2


def test_log_stats_scan_counters_together_and_preserve_null_and_empty_semantics(db_session):
    db_session.query(OperationLog).delete()
    now = datetime.datetime.now()
    db_session.add_all([
        OperationLog(username="甲" if index < 6 else "乙", action="查询" if index < 5 else "更新",
                     result="失败" if index < 2 else (None if index == 7 else "成功"),
                     create_time=now if index < 5 else now - datetime.timedelta(days=2))
        for index in range(8)
    ])
    db_session.commit()

    result, statements = count_selects(db_session, lambda: get_log_stats(current_user=None, db=db_session))
    assert len(statements) == 3
    assert result["data"] == {
        "total": 8, "failed": 2, "success_rate": "75.0%", "last_24h": 5,
        "top_users": [{"username": "甲", "count": 6}, {"username": "乙", "count": 2}],
        "top_actions": [{"action": "查询", "count": 5}, {"action": "更新", "count": 3}],
    }
    db_session.query(OperationLog).delete()
    db_session.commit()
    result, statements = count_selects(db_session, lambda: get_log_stats(current_user=None, db=db_session))
    assert len(statements) == 3
    assert result["data"] == {
        "total": 0, "failed": 0, "success_rate": "N/A", "last_24h": 0, "top_users": [], "top_actions": [],
    }
