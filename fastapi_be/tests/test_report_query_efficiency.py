from sqlalchemy import event

from app.routers.report import report_department_stats, report_doctor_workload


def _count_selects(engine, operation):
    statements = []

    def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        operation()
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return statements


def test_doctor_workload_uses_one_aggregate_query(seed_data, db_session):
    statements = _count_selects(
        db_session.get_bind(),
        lambda: report_doctor_workload({}, None, seed_data["admin_user"], db_session),
    )

    assert len(statements) == 1


def test_department_stats_uses_one_aggregate_query(seed_data, db_session):
    statements = _count_selects(
        db_session.get_bind(),
        lambda: report_department_stats({}, None, seed_data["admin_user"], db_session),
    )

    assert len(statements) == 1
