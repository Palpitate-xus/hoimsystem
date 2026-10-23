"""Actual mounted Main/JWT synthetic author-review-learner practice lifecycle."""

import datetime as dt
import hashlib
import json

import pytest
from sqlalchemy import event, text

from app.ai import clinical_training_contract as c
from app.ai.clinical_training_practice_models import AITrainingSubmission
from app.ai.models import AIAuditEvent
from app.models import OperationLog
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import observe_bodies, request
from tests.test_ai_clinical_training_reviews import proposal

BASE = "/api/ai/clinical-training"


@pytest.fixture
def http_case(reference_case, seed_data, auth_headers):
    db, author, reviewer, documents = reference_case
    value = request(reference_case)
    headers = {"author": auth_headers(author.username), "reviewer": auth_headers(reviewer.username), "learner": auth_headers(seed_data["doctor_user"].username), "patient": auth_headers(seed_data["patient_user"].username)}
    actors = dict(learner=seed_data["doctor_user"].user_id, reviewer=reviewer.user_id)
    db.commit()
    db.close()
    return db, value, headers, actors


async def course(client, case):
    db, value, headers, actors = case
    response = await client.post(BASE + "/lessons", headers=headers["author"], json=value)
    assert response.status_code == 200, response.text
    lesson = response.json()["data"]
    response = await client.post(BASE + f"/lessons/{lesson['lesson_id']}/reviews", headers=headers["reviewer"], json=proposal(lesson))
    assert response.status_code == 200, response.text
    return lesson, response.json()["data"]


def answers(value, lesson, review):
    return dict(review_id=review["review_id"], submission=dict(lesson_id=lesson["lesson_id"], public_source_sha256=lesson["public_hash"], answers=[dict(question_id=question["question_id"], selected_option_ids=question["correct_option_ids"]) for question in value["questions"]]))


def assert_no_protected_bodies(columns):
    assert not any(name == key or name.endswith("_" + key) for name in columns for key in ("private_json", "public_json", "references_json", "review_json", "content", "submission_json", "feedback_json"))


@pytest.mark.asyncio
async def test_actual_main_jwt_complete_independent_course_submission_bare_parts_and_withdrawal(http_case, async_client, tmp_path):
    db, value, headers, actors = http_case
    packets = []

    async def call(method, path, who, *, body=None, expected=200):
        response = await async_client.request(method, path, headers=headers[who], **({"json": body} if body is not None else {}))
        assert response.status_code == expected, (path, response.text)
        packets.append(dict(method=method, path=path, request_body=c.canonical_json(body) if body is not None else None, status=response.status_code, body=response.text, body_sha256=hashlib.sha256(response.content).hexdigest(), parts_wire=response.headers.get("X-AI-Parts-Wire"), public_source_sha256=response.headers.get("X-AI-Public-Source-SHA256"), review_id=response.headers.get("X-AI-Training-Review-ID")))
        return response

    created = await call("POST", BASE + "/lessons", "author", body=value)
    lesson = created.json()["data"]
    await call("POST", BASE + f"/lessons/{lesson['lesson_id']}/reviews", "author", body=proposal(lesson), expected=403)
    for part_name in ("private", "public", "references"):
        response = await call("GET", BASE + f"/lessons/{lesson['lesson_id']}/parts/{part_name}", "author")
        assert response.headers["X-AI-Parts-Wire"] == "canonical_json_body_no_envelope"
        assert response.content == c.whole(response.json()).encode()
    response = await call("POST", BASE + f"/lessons/{lesson['lesson_id']}/reviews", "reviewer", body=proposal(lesson))
    review = response.json()["data"]
    response = await call("GET", BASE + "/published-lessons", "learner")
    assert any(row["review_id"] == review["review_id"] and row["public_source_sha256"] == lesson["public_hash"] for row in response.json()["data"]["items"])
    response = await call("GET", BASE + f"/published-lessons/{review['review_id']}", "learner")
    assert response.headers["X-AI-Public-Source-SHA256"] == lesson["public_hash"] == hashlib.sha256(response.content).hexdigest()
    assert response.headers["X-AI-Training-Review-ID"] == review["review_id"]
    assert all(key not in response.text for key in ("correct_option_ids", "reviewed_rationale", "reference_ids", lesson["private_hash"]))
    response = await call("POST", BASE + "/submissions", "learner", body=answers(value, lesson, review))
    ack = response.json()["data"]
    assert ack["model_attempted"] is False and "feedback" not in ack
    # A fresh actual SQL read observes the committed submission and real Audit
    # before the next HTTP request can disclose a single answer key.
    stored = db.query(AITrainingSubmission).filter_by(submission_id=ack["submission_id"]).one()
    assert db.get(AIAuditEvent, stored.creation_event_id).action == "training_practice_submit"
    db.rollback()
    for part_name in ("submission", "feedback", "references"):
        response = await call("GET", BASE + f"/submissions/{ack['submission_id']}/parts/{part_name}", "learner")
        assert response.headers["X-AI-Parts-Wire"] == "canonical_json_body_no_envelope" and response.content == c.whole(response.json()).encode()
        if part_name == "feedback":
            assert response.json()["matching_count"] == response.json()["question_count"] == 2
        elif part_name == "references":
            assert len(response.json()["references"]) == 2 and "source_uri" not in response.text and "token_invalid_before" not in response.text
    await call("GET", BASE + f"/submissions/{ack['submission_id']}/parts/feedback", "author", expected=403)
    for path, who in [("/lessons", "author"), ("/reviews", "author"), ("/submission-management", "author"), ("/submissions", "learner")]:
        columns, observer = observe_bodies(db)
        try:
            response = await call("GET", BASE + path, who)
        finally:
            event.remove(db.get_bind(), "after_cursor_execute", observer)
        assert_no_protected_bodies(columns)
    await call("POST", BASE + f"/lessons/{lesson['lesson_id']}/revoke", "author", body=dict(revision=1, reason="真实Main/JWT合成课程撤回"))
    columns, observer = observe_bodies(db)
    try:
        await call("GET", BASE + f"/submissions/{ack['submission_id']}/parts/feedback", "learner", expected=403)
        await call("GET", BASE + f"/lessons/{lesson['lesson_id']}/parts/private", "author", expected=403)
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_no_protected_bodies(columns)
    logs = db.query(OperationLog).filter(OperationLog.path.like(BASE + "%")).all()
    assert any(row.method == "GET" and "/parts/feedback" in row.path for row in logs)
    assert not any("PRIVATE_REVIEWED_RATIONALE_SENTINEL" in str(row.detail) or "accesstoken" in str(row.detail) for row in logs)
    (tmp_path / "actual-main-training-source-practice-packets.json").write_text(json.dumps(dict(schema_version="clinical_training_actual_main_packets_v1", scope="One actual mounted Main/JWT synthetic Source and fixed local practice lifecycle, no model or clinical claim; request/response bodies exact, no JWT captured", lesson_id=lesson["lesson_id"], review_id=review["review_id"], submission_id=ack["submission_id"], packets=packets), ensure_ascii=False, indent=2) + "\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["?patient_id=1", "?page=1&page=2", "?size=51", "?page=0", "?size=1.5", "?research_project_id=1"])
async def test_actual_main_training_directories_reject_foreign_duplicate_or_out_of_bounds_scope_before_body(http_case, async_client, query):
    db, value, headers, actors = http_case
    columns, observer = observe_bodies(db)
    try:
        response = await async_client.get(BASE + "/published-lessons" + query, headers=headers["learner"])
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert response.status_code == 422, response.text
    assert_no_protected_bodies(columns)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["patient", "reviewer_epoch", "learner_epoch"])
async def test_actual_main_current_jwt_roles_and_epochs_deny_before_source_bodies(http_case, async_client, fault):
    db, value, headers, actors = http_case
    lesson, review = await course(async_client, http_case)
    who = "patient" if fault == "patient" else "learner"
    if fault != "patient":
        identifier = actors["reviewer" if fault == "reviewer_epoch" else "learner"]
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:id"), dict(clock=dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(seconds=1), id=identifier))
        db.commit()
    columns, observer = observe_bodies(db)
    try:
        response = await async_client.get(BASE + f"/published-lessons/{review['review_id']}", headers=headers[who])
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert response.status_code in {401, 403}, response.text
    assert_no_protected_bodies(columns)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b'{"title":"one","title":"two"}', b'{"score":1.5}', b'{"score":NaN}', b'{"title":"\xff"}'])
async def test_actual_main_bounded_training_parser_rejects_ambiguous_fraction_nonfinite_and_invalid_utf8(http_case, async_client, raw):
    response = await async_client.post(BASE + "/lessons", headers={**http_case[2]["author"], "content-type": "application/json"}, content=raw)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_actual_main_training_whole_request_above_8mib_is_413_without_truncation(http_case, async_client):
    response = await async_client.post(BASE + "/lessons", headers={**http_case[2]["author"], "content-type": "application/json"}, content=b" " * (8388608 + 1))
    assert response.status_code == 413, response.text
