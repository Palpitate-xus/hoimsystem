"""Actual workbook parsing and SQL boundaries for inventory-only bulk imports."""

import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import Workbook
from sqlalchemy import event, text

from app.ai.inventory_native_source_models import AIInventoryWriteGate
from app.models import Pharmaceutical
from app.routers import data_import_export as router


def workbook(entity, *, rows=(), headers=None):
    document = Workbook()
    document.active.append(router.ENTITY_HEADERS[entity] if headers is None else headers)
    for row in rows:
        document.active.append(row)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    buffer.seek(0)
    return UploadFile(file=buffer, filename="synthetic.xlsx")


def test_pharmaceutical_import_rechecks_stale_actual_role_after_workbook_validation(db_session, seed_data):
    db, actor = db_session, seed_data["admin_user"]
    name = "synthetic-role-" + uuid.uuid4().hex
    upload = workbook("pharmaceuticals", rows=[(name, 3, "1.20", None, None, None, 0, 0)])
    db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:pk"), {"pk": actor.user_id})
    assert actor.user_role == "admin"
    try:
        with pytest.raises(HTTPException) as error:
            router.import_data("pharmaceuticals", upload, current_user=actor, db=db)
        assert error.value.status_code == 403
        assert db.query(Pharmaceutical).filter_by(name=name).count() == 0
        assert actor.user_role == "patient"
    finally:
        upload.file.close()
        db.rollback()


def test_inventory_import_owns_normal_commit_and_preserves_existing_stock(db_session, seed_data):
    db = db_session
    original = [(row.pharmaceutical_id, row.stock) for row in db.query(Pharmaceutical).all()]
    name = "synthetic-import-" + uuid.uuid4().hex
    upload = workbook("pharmaceuticals", rows=[(name, 3, "1.20", None, None, None, 0, 0)])
    try:
        response = router.import_data("pharmaceuticals", upload, current_user=seed_data["admin_user"], db=db)
    finally:
        upload.file.close()
    assert response["code"] == 200 and response["data"]["imported"] == 1
    assert db.query(AIInventoryWriteGate).count() == 1
    assert db.query(Pharmaceutical).filter_by(name=name).one().stock == 3
    assert [
        (row.pharmaceutical_id, row.stock) for row in db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id.in_([pk for pk, _ in original])).order_by(Pharmaceutical.pharmaceutical_id).all()
    ] == sorted(original)


@pytest.mark.parametrize("entity", ["doctors", "patients"])
def test_non_inventory_import_never_acquires_inventory_gate(db_session, seed_data, entity):
    sql = []

    def collect(conn, cursor, statement, parameters, context, executemany):
        sql.append(statement)

    upload = workbook(entity)
    event.listen(db_session.get_bind(), "before_cursor_execute", collect)
    try:
        response = router.import_data(entity, upload, current_user=seed_data["admin_user"], db=db_session)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", collect)
        upload.file.close()
    assert response["code"] == 200 and response["data"]["imported"] == 0
    assert not any("hoimsystem_ai_inventory_write_gate" in statement for statement in sql)


def test_invalid_workbook_is_refused_before_gate_or_actor_read(db_session, seed_data):
    sql = []

    def collect(conn, cursor, statement, parameters, context, executemany):
        sql.append(statement)

    actor = seed_data["admin_user"]
    db_session.expire(actor)
    upload = workbook("pharmaceuticals", headers=["name"])
    event.listen(db_session.get_bind(), "before_cursor_execute", collect)
    try:
        with pytest.raises(HTTPException) as error:
            router.import_data("pharmaceuticals", upload, current_user=actor, db=db_session)
        assert error.value.status_code == 400
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", collect)
        upload.file.close()
    assert sql == []
