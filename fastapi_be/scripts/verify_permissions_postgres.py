"""Exercise real API authorization against the disposable local PostgreSQL DB.

Run with the project's test virtualenv. Credentials are read only from the
private verification env file; this script cannot accept an application DSN.
Use --reset solely to repeat this disposable verification database run.
"""

import argparse
import asyncio
import datetime
import json
import os
import secrets
import stat
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_ENV = ROOT / ".local-preview/permissions-postgres-test.env"
REPORT = ROOT / ".local-preview/permissions-postgres-verification.json"
WRITE_CODE = "PUT /api/access/policies/{kind}/{key}"


def test_database_url():
    from sqlalchemy.engine import URL

    if stat.S_IMODE(PRIVATE_ENV.stat().st_mode) != 0o600 or PRIVATE_ENV.stat().st_uid != os.getuid():
        raise RuntimeError("Verification credentials require owner-only mode 0600")
    values = dict(line.split("=", 1) for line in PRIVATE_ENV.read_text().splitlines() if line and not line.startswith("#"))
    name = values["POSTGRES_DB"]
    if not name.startswith(("hoim_permissions", "permissions_")):
        raise RuntimeError("Only the dedicated permission verification database is allowed")
    return URL.create("postgresql+psycopg2", username=values["POSTGRES_USER"], password=values["POSTGRES_PASSWORD"], host="127.0.0.1", port=51946, database=name)


def bootstrap(engine, *, reset):
    from alembic.config import Config
    from sqlalchemy import inspect, text

    from alembic import command
    from app.security import hash_password

    with engine.begin() as connection:
        assert connection.scalar(text("SELECT current_database()")) == engine.url.database
        tables = inspect(connection).get_table_names()
        if tables and not reset:
            raise RuntimeError("Disposable database already has tables; use --reset to repeat verification")
        if reset:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        connection.execute(
            text("""CREATE TABLE hoimsystem_users (
            user_id SERIAL PRIMARY KEY, username VARCHAR(20), password VARCHAR(128),
            user_role VARCHAR(20), token_invalid_before TIMESTAMP NULL
        )""")
        )
        connection.execute(
            text("INSERT INTO hoimsystem_users(username,password,user_role) VALUES (:name,:password,:role)"),
            [
                {"name": "pg_super", "password": hash_password("pg-verify-password"), "role": "super_admin"},
                {"name": "pg_admin", "password": hash_password("pg-verify-password"), "role": "admin"},
            ],
        )
    config = Config(str(ROOT / "fastapi_be/alembic.ini"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    command.stamp(config, "20261028_audit_covering")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        subjects = connection.execute(text("SELECT auth_subject FROM hoimsystem_users")).scalars().all()
        assert len(subjects) == 2 and len(set(subjects)) == 2 and all(len(value) == 32 for value in subjects)
        assert any(index["unique"] and index["column_names"] == ["auth_subject"] for index in inspect(connection).get_indexes("hoimsystem_users"))
        assert not next(column for column in inspect(connection).get_columns("hoimsystem_users") if column["name"] == "auth_subject")["nullable"]
        required = {"hoimsystem_access_policy", "hoimsystem_access_policy_audit", "hoimsystem_access_policy_guard"}
        assert required <= set(inspect(connection).get_table_names())
        assert connection.scalar(text("SELECT count(*) FROM hoimsystem_access_policy_guard WHERE id=1")) == 1
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    return {"from": "20261028_audit_covering", "to": revision, "legacy_accounts_backfilled": 2, "subjects_unique_nonnull": True, "policy_tables_and_single_guard": True}


async def verify(engine, summary):
    import httpx
    from fastapi import Request
    from sqlalchemy import event, text
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.access_control import base_permissions
    from app.access_models import AccessPolicyAudit
    from app.database import Base, get_db
    from app.main import app
    from app.models import User
    from app.routers import permission_management
    from app.security import hash_password

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    database.SessionLocal = factory

    async def discard_event(*_args, **_kwargs):
        return None

    permission_management.publish_event = discard_event

    def request_db(request: Request):
        with factory() as db:
            tag = request.headers.get("x-verification-case", "ordinary")

            @event.listens_for(db, "after_begin")
            def tag_connection(_session, _transaction, connection):
                connection.info["permission_verification"] = tag

            yield db

    app.dependency_overrides[get_db] = request_db
    with factory() as db:
        doctor = User(username="pg_doctor", password=hash_password("pg-verify-password"), user_role="doctor")
        db.add(doctor)
        db.commit()
        doctor_id = doctor.user_id
        admin_id = db.query(User.user_id).filter_by(username="pg_admin").scalar()

    state = {"mode": None, "pids": set()}
    barrier = threading.Barrier(2)
    admin_waiting = threading.Event()
    locked = threading.Event()
    release = threading.Event()

    def before_sql(connection, cursor, statement, parameters, context, many):
        normalized = statement.lower()
        tag = connection.info.get("permission_verification")
        is_guard = "select" in normalized and "hoimsystem_access_policy_guard" in normalized and "for update" in normalized
        if is_guard:
            state["pids"].add(cursor.connection.get_backend_pid())
            if state["mode"] == "version" and tag == "same_version":
                barrier.wait(timeout=15)
            if state["mode"] == "revoke" and tag == "revoke_admin":
                admin_waiting.set()
        if state["mode"] == "user_lock" and tag == "lock_owner" and "for update" in normalized:
            locked.set()

    def after_sql(connection, cursor, statement, parameters, context, many):
        tag = connection.info.get("permission_verification")
        normalized = statement.lower()
        if state["mode"] == "revoke" and tag == "revoke_super" and "hoimsystem_access_policy_guard" in normalized and "for update" in normalized:
            if not admin_waiting.wait(timeout=15):
                raise RuntimeError("Concurrent administrator did not reach the real PostgreSQL guard")

    event.listen(engine, "before_cursor_execute", before_sql)
    event.listen(engine, "after_cursor_execute", after_sql)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://verification", timeout=30) as client:

        async def login(username):
            response = await client.post("/api/login", json={"username": username, "password": "pg-verify-password"})
            assert response.status_code == 200 and response.json()["code"] == 200
            return {"accesstoken": response.json()["data"]["accesstoken"]}

        super_header, admin_header, doctor_header = await asyncio.gather(login("pg_super"), login("pg_admin"), login("pg_doctor"))

        async def put(headers, user_id, version, *, permissions=None, tag="ordinary"):
            return await client.put(f"/api/access/policies/user/{user_id}", headers={**headers, "x-verification-case": tag}, json={"expected_version": version, "allowed_permissions": permissions})

        state["mode"] = "version"
        responses = await asyncio.wait_for(asyncio.gather(put(super_header, doctor_id, 0, tag="same_version"), put(admin_header, doctor_id, 0, tag="same_version")), 25)
        state["mode"] = None
        assert sorted(response.status_code for response in responses) == [200, 409]
        with factory() as db:
            count = db.query(AccessPolicyAudit).filter_by(subject=f"user:{doctor_id}").count()
        assert count == 1 and len(state["pids"]) >= 2
        summary["version_conflict"] = {"http_statuses": sorted(response.status_code for response in responses), "policy_audits": count, "distinct_postgres_connections": len(state["pids"])}

        state["mode"] = "revoke"
        allowed = sorted(base_permissions("admin") - {WRITE_CODE})
        responses = await asyncio.wait_for(asyncio.gather(put(super_header, admin_id, 0, permissions=allowed, tag="revoke_super"), put(admin_header, doctor_id, 1, tag="revoke_admin")), 25)
        state["mode"] = None
        assert [response.status_code for response in responses] == [200, 403]
        with factory() as db:
            assert db.query(AccessPolicyAudit).filter_by(subject=f"user:{doctor_id}").count() == 1
        summary["concurrent_admin_revocation"] = {"super_revocation_status": 200, "queued_admin_write_status": 403, "rejected_write_audits": 0}

        async def read(index):
            headers = super_header if index % 2 else admin_header
            started = time.perf_counter()
            response = await client.get("/api/access/me", headers=headers)
            elapsed = (time.perf_counter() - started) * 1000
            assert response.status_code == 200
            assert (WRITE_CODE in response.json()["data"]["permission_codes"]) is bool(index % 2)
            return elapsed

        started = time.perf_counter()
        timings = await asyncio.wait_for(asyncio.gather(*(read(index) for index in range(50))), 45)
        summary["concurrent_reads"] = {
            "requests": 50,
            "concurrency": 50,
            "correct_responses": 50,
            "total_ms": round((time.perf_counter() - started) * 1000, 2),
            "p95_ms": round(sorted(timings)[47], 2),
            "max_ms": round(max(timings), 2),
            "transport": "ASGI FastAPI with real TCP PostgreSQL",
        }

        assert (await client.get("/api/access/catalog", headers=admin_header)).status_code == 200
        allowed = sorted(base_permissions("admin") - {WRITE_CODE, "GET /api/access/catalog"})
        assert (await put(super_header, admin_id, 1, permissions=allowed)).status_code == 200
        assert (await client.get("/api/access/catalog", headers=admin_header)).status_code == 403
        assert (await client.get("/api/access/me", headers=admin_header)).status_code == 200
        summary["existing_token_revocation"] = {"before_status": 200, "next_request_status": 403, "token_reissued": False}

        def hold_user():
            with engine.begin() as connection:
                connection.info["permission_verification"] = "lock_owner"
                connection.execute(text("SELECT user_id FROM hoimsystem_users WHERE user_id=:id FOR UPDATE"), {"id": doctor_id})
                if not release.wait(timeout=15):
                    raise RuntimeError("Timed-out disposable user-row lock")

        state["mode"] = "user_lock"
        holder = asyncio.create_task(asyncio.to_thread(hold_user))
        assert await asyncio.to_thread(locked.wait, 10)
        policy_task = asyncio.create_task(put(super_header, doctor_id, 1))
        role_task = asyncio.create_task(client.post("/api/user/updateRole", headers=super_header, json={"user_id": doctor_id, "user_role": "nurse"}))
        # Let both real requests reach the held user row; release is controlled
        # by this harness and never changes production request lock ordering.
        await asyncio.sleep(0.15)
        release.set()
        await holder
        policy_response, role_response = await asyncio.wait_for(asyncio.gather(policy_task, role_task), 20)
        state["mode"] = None
        assert policy_response.status_code in {200, 409} and role_response.status_code == 200 and role_response.json()["code"] == 200
        summary["user_and_guard_lock_order"] = {"policy_status": policy_response.status_code, "account_status": role_response.status_code, "deadlock": False}

    event.remove(engine, "before_cursor_execute", before_sql)
    event.remove(engine, "after_cursor_execute", after_sql)
    summary["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Reset only the dedicated disposable verification schema")
    arguments = parser.parse_args()
    url = test_database_url()
    # Override ambient application settings before any app import.
    os.environ.update(
        DATABASE_URL=url.render_as_string(hide_password=False),
        ENVIRONMENT="test",
        SECRET_KEY=secrets.token_hex(32),
        AUTO_CREATE_SCHEMA="false",
        SCHEDULER_ENABLED="false",
        REDIS_URL="",
        DB_POOL_SIZE="40",
        DB_MAX_OVERFLOW="20",
        DB_STATEMENT_TIMEOUT_MS="20000",
        LIS_OUTBOUND_URL="",
        PACS_OUTBOUND_URL="",
        PAYMENT_OUTBOUND_URL="",
        MEDICAL_INSURANCE_OUTBOUND_URL="",
    )
    sys.path.insert(0, str(ROOT / "fastapi_be"))
    from sqlalchemy import create_engine

    engine = create_engine(url, pool_size=40, max_overflow=20, pool_pre_ping=True, connect_args={"options": "-c statement_timeout=20000 -c lock_timeout=15000"}, echo=False)
    summary = {"generated_at": datetime.datetime.now(datetime.UTC).isoformat(), "database": "disposable PostgreSQL on loopback port 51946", "passed": False}
    try:
        summary["migration"] = bootstrap(engine, reset=arguments.reset)
        asyncio.run(verify(engine, summary))
    except Exception as error:
        summary["error_type"] = type(error).__name__
        REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        raise SystemExit(f"Disposable PostgreSQL verification failed ({type(error).__name__}); inspect the local summary") from None
    finally:
        engine.dispose()
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
