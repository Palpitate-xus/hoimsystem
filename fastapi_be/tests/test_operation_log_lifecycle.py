"""Hold real yield cleanup open to prove audit runs after the request stack."""

import asyncio

import pytest
from fastapi import BackgroundTasks, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app import database
from app.main import OperationLogMiddleware
from app.models import OperationLog
from tests.conftest import TestingSessionLocal


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_error", [False, True])
async def test_audit_waits_for_actual_yield_cleanup_and_preserves_background_and_error(db_session, monkeypatch, cleanup_error):
    entered = asyncio.Event()
    release = asyncio.Event()
    audit_started = asyncio.Event()
    loop = asyncio.get_running_loop()
    stages = []
    early = []
    closed = False

    async def request_session():
        nonlocal closed
        db = TestingSessionLocal()
        try:
            db.query(OperationLog).count()
            yield db
        finally:
            stages.append("dependency_closing")
            entered.set()
            await release.wait()
            db.close()
            closed = True
            stages.append("dependency_closed")
            if cleanup_error:
                raise RuntimeError("synthetic original cleanup failure")

    def audit_session():
        stages.append("audit_session")
        early.append(not closed)
        loop.call_soon_threadsafe(audit_started.set)
        return TestingSessionLocal()

    monkeypatch.setattr(database, "SessionLocal", audit_session)
    app = FastAPI()
    app.add_middleware(OperationLogMiddleware)

    @app.post("/synthetic/operation/create")
    async def handler(request: Request, background_tasks: BackgroundTasks, db=Depends(request_session)):
        request.state.auth_identity = (None, "synthetic-lifecycle-user", "super_admin")
        background_tasks.add_task(stages.append, "business_background_finished")
        return {"code": 200, "data": {"literal": "原文2026-10-21T12:00:00.123456Z"}}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic") as client:
        task = asyncio.create_task(client.post("/synthetic/operation/create", params={"id": "cleanup-" + str(cleanup_error)}))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            # The dependency is deliberately held open. This bounded probe gives
            # the previous response-background audit a chance to expose its
            # forbidden entry; the passing implementation cannot enter at all.
            try:
                await asyncio.wait_for(audit_started.wait(), timeout=0.15)
            except TimeoutError:
                pass
        finally:
            release.set()
        if cleanup_error:
            with pytest.raises(RuntimeError, match="synthetic original cleanup failure"):
                await task
        else:
            response = await task
            assert response.status_code == 200
            assert response.json()["data"]["literal"] == "原文2026-10-21T12:00:00.123456Z"
    assert early == [False], "Audit opened a database session before actual request cleanup completed"
    assert stages.count("business_background_finished") == stages.count("audit_session") == 1
    assert stages.index("business_background_finished") < stages.index("dependency_closed") < stages.index("audit_session")
    db_session.expire_all()
    rows = db_session.query(OperationLog).filter_by(path="/synthetic/operation/create", detail="id=cleanup-" + str(cleanup_error)).all()
    assert len(rows) == 1
    assert rows[0].username == "synthetic-lifecycle-user" and rows[0].status_code == 200


@pytest.mark.asyncio
async def test_auth_failure_audit_retains_username_and_existing_background_without_password(db_session, monkeypatch):
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    stages = []
    app = FastAPI()
    app.add_middleware(OperationLogMiddleware)

    @app.post("/api/login")
    async def login(background_tasks: BackgroundTasks):
        background_tasks.add_task(stages.append, "business_background")
        return JSONResponse(status_code=403, content={"code": 403, "msg": "synthetic denied"}, background=background_tasks)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic") as client:
        response = await client.post("/api/login", json={"username": "synthetic-attempt", "password": "synthetic-never-log-password"})
    assert response.status_code == 403 and response.json()["msg"] == "synthetic denied"
    assert stages == ["business_background"]
    row = db_session.query(OperationLog).filter_by(path="/api/login").one()
    assert row.username == "synthetic-attempt(attempt)" and row.status_code == 403 and row.result == "失败"
    assert "synthetic-never-log-password" not in (row.detail or "")
