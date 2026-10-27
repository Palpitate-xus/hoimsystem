"""The documented API must remain readable with nested source discriminators."""

from app.main import app


def test_complete_openapi_schema_has_valid_discriminator_mappings():
    document = app.openapi()
    assert "/api/ai/surgery-sources/{kind}" in document["paths"]
    assert len(document["paths"]) >= 1000

    def inspect(node):
        if isinstance(node, dict):
            discriminator = node.get("discriminator")
            if isinstance(discriminator, dict):
                assert all(isinstance(value, str) for value in discriminator.get("mapping", {}).values())
            for value in node.values():
                inspect(value)
        elif isinstance(node, list):
            for value in node:
                inspect(value)

    inspect(document)


def test_surgery_source_schema_keeps_nested_payload_alternatives_and_closed_body():
    document = app.openapi()
    route = document["paths"]["/api/ai/surgery-sources/{kind}"]["post"]
    reference = route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    body = document["components"]["schemas"][reference.rsplit("/", 1)[-1]]
    assert body["additionalProperties"] is False
    assert len(body["properties"]["payload"]["oneOf"]) >= 8
    assert "professional_attestation" in body["required"]
