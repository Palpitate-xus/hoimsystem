"""Exercise the real application with an exhausted, bounded connection pool."""

import httpx
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.database import Base, get_db
from app.main import app
from app.models import Prescription, User
from app.routers.user import create_access_token


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [("GET", "/api/patientManagement/getList"), ("POST", "/api/prescriptionManagement/create")])
async def test_real_api_reports_pool_exhaustion_without_writing(tmp_path, monkeypatch, method, path):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "bounded.sqlite3"),
        poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=0.05,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="isolated-pool-probe", password="unused", user_role="admin")
        session.add(user)
        session.commit()
        # A real account binding reaches the exhausted pool; a malformed token
        # correctly stops at authentication before requesting a connection.
        headers = {"accesstoken": create_access_token(user.username, user=user)}

    def isolated_db():
        with Session(engine) as session:
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_db, isolated_db)
    try:
        with engine.connect():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
                response = await client.request(method, path, headers=headers, **({"json": {}} if method == "POST" else {}))
            assert response.status_code == 503, response.text
            assert response.headers["retry-after"] == "1"
            assert response.json() == {"code": 503, "msg": "数据库连接繁忙，请稍后重试"}
            assert "QueuePool" not in response.text and "bounded.sqlite3" not in response.text
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
            assert connection.execute(select(func.count()).select_from(Prescription)).scalar_one() == 0
    finally:
        engine.dispose()
