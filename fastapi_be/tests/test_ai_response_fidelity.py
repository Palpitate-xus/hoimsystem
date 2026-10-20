"""Reviewers must receive the exact clinical text whose version hash they approve."""

import uuid

import pytest

from app.ai.governance import digest


@pytest.mark.asyncio
async def test_review_response_does_not_rewrite_timestamps_inside_knowledge_text(seed_data, async_client, auth_headers):
    content = '原记录时刻2026-10-20T10:12:13.123456+00:00；嵌套原文{"time":"2026-10-20 10:12:14.987654"}，小数和原始文本须逐字保留供审核。'
    headers = auth_headers("super01")
    created = await async_client.post(
        "/api/ai/admin/knowledge",
        headers=headers,
        json={
            "title": "原文完整性验证",
            "version": str(uuid.uuid4()),
            "source_uri": "hospital://isolated/response-fidelity",
            "category": "clinical",
            "feature_keys": ["guideline_qa"],
            "content": content,
        },
    )
    assert created.status_code == 200, created.text
    document_id = created.json()["data"]["document_id"]
    response = await async_client.get("/api/ai/admin/knowledge/" + document_id, headers=headers)
    assert response.status_code == 200
    detail = response.json()["data"]
    assert detail["content"] == content
    assert detail["content_hash"] == digest(detail["content"])
