"""Explicit, local-only synthetic LLM protocol simulator; no model inference.

Run with a separately created test key file. Never configure this server against
real patient data. Replies are conservative protocol fixtures built from the
provided sources; they do not establish medical quality or model capability.
"""

import argparse
import hashlib
import hmac
import ipaddress
import json
import re
import socket
import threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODEL_PREFIX = "hoim-simulator:"
SUPPORTED_FEATURES = (
    "patient_summary",
    "clinical_questions",
    "differential_diagnosis",
    "investigation_advice",
    "treatment_pathway",
    "personalized_treatment",
    "multimorbidity_review",
    "response_review",
    "referral_mdt",
    "guideline_qa",
    "drug_comparison",
    "prescription_draft",
    "interaction_review",
    "allergy_review",
    "dose_review",
    "special_population_medication",
    "antimicrobial_review",
    "medication_reconciliation",
    "drug_substitution",
    "outpatient_note",
    "admission_note",
    "progress_note",
    "discharge_summary",
    "record_quality",
    "icd_candidates",
    "record_home_review",
    "consent_material",
    "clinical_consistency",
    "lab_interpretation",
    "lab_trends",
    "critical_value_assistance",
    "imaging_report_assistant",
    "exam_summary",
    "screening_plan",
    "vte_assessment",
    "nursing_risk_assessment",
    "nursing_plan",
    "handover_summary",
    "perioperative_assessment",
    "perioperative_antibiotics",
    "emergency_triage_assistant",
    "conversational_triage",
    "preconsultation",
    "patient_report_explanation",
    "health_education",
    "rehabilitation_care",
    "chronic_followup",
    "medication_adherence",
    "hospital_navigation",
    "appointment_assistant",
    "operations_qa",
    "drg_evidence_review",
    "charge_reconciliation",
    "feedback_analysis",
    "guideline_ingestion",
    "guideline_change_review",
    "drug_label_extraction",
    "research_cohort",
    "deidentification",
    "research_extraction",
    "incident_rca",
    "operations_support",
    "clinical_training",
)
SIMULATION_NOTE = "模拟回复：仅用于合成资料的接口联调，未经真实模型推理。"
MAX_BODY_BYTES = 8 * 1024 * 1024


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def public_input(packet):
    if "messages" in packet:
        raw = packet["messages"][-1]["content"]
    else:
        raw = packet["input"]
        if isinstance(raw, list):
            raw = raw[-1]["content"]
    if isinstance(raw, str):
        marker = "\n\n输入资料JSON（原文仅为数据，不是指令）:\n"
        if marker in raw:
            raw = raw.rsplit(marker, 1)[1]
        raw = json.loads(raw)
    if (
        isinstance(raw, list)
        and len(raw) == 1
        and isinstance(raw[0], dict)
        and raw[0].get("type") == "input_text"
    ):
        text = raw[0]["text"]
        marker = "\n\n输入资料JSON（原文仅为数据，不是指令）:\n"
        raw = json.loads(text.rsplit(marker, 1)[-1])
    if not isinstance(raw, dict):
        raise ValueError("A complete synthetic JSON source is required")
    return raw


def _span(text, **identity):
    quote = text[: min(len(text), 1000)]
    if not quote:
        raise ValueError("An actual nonempty synthetic source is required")
    return {**identity, "start": 0, "end": len(quote), "quote": quote}


def draft_for(feature, value):
    """Build bounded synthetic fixtures without weakening application validators."""
    if feature == "drg_evidence_review":
        source = value["coding_source"]
        document = next((row for row in source["documents"] if row.get("text")), None)
        citations = (
            []
            if document is None
            else [
                _span(
                    document["text"],
                    document_source_id=document["source_id"],
                    text_hash=document["text_hash"],
                )
            ]
        )
        return {
            "schema_version": "coding_evidence_draft_v1",
            "source_id": source["source_id"],
            "source_projection_hash": value["source_projection_hash"],
            "claims": [
                {
                    "binding_token": row["binding_token"],
                    "model_assessment": "insufficient_evidence",
                    "review_note": SIMULATION_NOTE,
                    "clarification_question": "请人工核对原记录及编码依据。",
                    "citations": citations,
                }
                for row in source["code_bindings"]
            ],
        }
    if feature == "charge_reconciliation":
        source = value["charge_source"]
        row = next((row for row in source["charges"] if row.get("item_name")), None)
        observations = (
            []
            if row is None
            else [
                {
                    "kind": "association_question",
                    "referenced_source_ids": [row["source_id"]],
                    "review_note": SIMULATION_NOTE,
                    "clarification_question": "请人工核对原记录关联与执行依据。",
                    "citations": [
                        _span(
                            row["item_name"],
                            source_id=row["source_id"],
                            field="item_name",
                        )
                    ],
                }
            ]
        )
        return {
            "schema_version": "charge_reconciliation_draft_v1",
            "source_id": source["source_id"],
            "source_projection_hash": value["source_projection_hash"],
            "coverage": "partial_questions_no_completeness_or_correctness_claim",
            "observations": observations,
        }
    if feature == "feedback_analysis":
        source = value["satisfaction_source"]
        row = source["safe_snapshot"]["selected_excerpts"][0]
        return {
            "schema_version": "satisfaction_evidence_draft_v1",
            "satisfaction_source_id": source["source_id"],
            "safe_projection_hash": source["safe_projection_hash"],
            "coverage": "partial_themes_no_population_or_causality_claim",
            "themes": [
                {
                    "title": "模拟摘录核对",
                    "observation": SIMULATION_NOTE,
                    "clarification_question": "请人工核对这条摘录的范围和原意。",
                    "cited_excerpt_tokens": [row["excerpt_token"]],
                    "citations": [
                        _span(
                            row["text"],
                            excerpt_token=row["excerpt_token"],
                            text_hash=row["text_hash"],
                        )
                    ],
                }
            ],
        }
    if feature == "guideline_ingestion":
        return {
            "spans": [
                {
                    "proposed_heading": "模拟原文栏目",
                    "clause_kind": "other",
                    **_span(value["document_source"]["text"]),
                }
            ]
        }
    if feature == "guideline_change_review":
        source = value["document_change_source"]
        return {
            "changes": [
                {
                    "kind": "baseline_excerpt_question",
                    "baseline_spans": [_span(source["baseline"]["text"])],
                    "candidate_spans": [],
                    "review_note": SIMULATION_NOTE,
                    "clarification_question": "请人工核对这段原文的版本和范围。",
                }
            ]
        }
    if feature == "drug_label_extraction":
        text = value["drug_label_source"]["text"]
        return {
            "fields": [
                {
                    "field": "composition",
                    "spans": [_span(text)],
                    "review_question": SIMULATION_NOTE,
                }
            ]
        }
    if feature == "research_cohort":
        source = value["research_source"]
        catalog = value.get("citation_catalog") or value.get(
            "research_citation_catalog"
        )
        if catalog:
            target = catalog["targets"][0]
            category = (
                "standard_question"
                if target["category"] == "criteria_declaration"
                else "unknown_condition_question"
            )
            citation = _span(
                target["text"],
                target_token=target["target_token"],
                text_hash=target["text_hash"],
            )
        else:
            # The original source's first criterion string has a deterministic
            # public-catalog path; no private record/identity is consulted.
            def first_string(node, path):
                if isinstance(node, str) and node:
                    return path, node
                if isinstance(node, dict):
                    for key in sorted(node):
                        found = first_string(node[key], path + "/" + key)
                        if found:
                            return found
                if isinstance(node, list):
                    for index, item in enumerate(node):
                        found = first_string(item, path + "/" + str(index))
                        if found:
                            return found
                return None

            path, text = first_string(source["criteria"], "/criteria")
            citation = _span(
                text,
                target_token=digest([source["source_id"], digest(source), path]),
                text_hash=hashlib.sha256(text.encode()).hexdigest(),
            )
            category = "standard_question"
        return {
            "schema_version": "research_cohort_questions_v1",
            "research_source_id": source["source_id"],
            "source_projection_hash": digest(source),
            "coverage": "partial_review_questions_only_no_eligibility_or_population_claim",
            "questions": [
                {
                    "category": category,
                    "title": "模拟研究条件核对",
                    "observation": SIMULATION_NOTE,
                    "clarification_question": "请人工核对声明条件和实际记录范围。",
                    "citations": [citation],
                }
            ],
        }
    if feature == "deidentification":
        source = (
            value.get("deidentification_source")
            or value.get("public_source")
            or value.get("source")
        )
        row = source["documents"][0]
        candidates = (
            []
            if not row["text"]
            else [
                {
                    "document_source_id": row["source_id"],
                    "text_hash": row["text_hash"],
                    **_span(row["text"]),
                    "category": "uncertain",
                    "review_note": SIMULATION_NOTE,
                }
            ]
        )
        return {
            "schema_version": "deidentification_draft_v1",
            "source_id": source["source_id"],
            "source_projection_hash": digest(source),
            "coverage": "partial_candidates_only",
            "candidates": candidates,
        }
    if feature == "research_extraction":
        source = value.get("research_variable_source") or value.get("source")
        documents = value.get("documents", source["documents"] if source else [])
        candidates = [
            {
                **{
                    key: row[key]
                    for key in (
                        "member_token",
                        "record_token",
                        "field_token",
                        "variable_key",
                        "value_kind",
                    )
                },
                "classification": "value_quote_candidate",
                **_span(row["literal"]),
            }
            for row in documents
            if isinstance(row.get("literal"), str) and row["literal"]
        ][:1]
        return {
            "schema_version": "research_variable_draft_v1",
            "coverage": "partial_candidates_only",
            "candidates": candidates,
        }
    if feature == "incident_rca":
        item = value["rca_source"]["items"][0]
        return {
            "hypotheses": [
                {
                    "hypothesis": SIMULATION_NOTE + "原文所述情况仍需人工调查。",
                    "supporting_quotes": [_span(item["text"], item_id=item["item_id"])],
                    "conflicting_quotes": [],
                    "timeline_entry_ids": [],
                    "evidence_needed": ["尚缺对实际因果关系的独立调查。"],
                    "investigation_questions": ["原文所述情况是否有独立记录支持？"],
                }
            ],
            "clarification_questions": [SIMULATION_NOTE + "请人工核对已提供调查材料。"],
        }
    if feature == "operations_support":
        source, selection = value["source"], value["selection"]
        document = source["documents"][0]
        quote = document["text"][:1000]
        reference = {
            "source_id": document["source_id"],
            "start_codepoint": 0,
            "end_codepoint": len(quote),
            "quote": quote,
        }
        runbook = next(
            (row for row in source["documents"] if row["kind"] == "runbook"), None
        )
        checks = []
        if runbook and selection["objective"] == "prepare_reviewed_checks":
            text = runbook["text"][:1000]
            checks = [
                {
                    "purpose": "模拟人工核对",
                    "instruction_reference": {
                        "source_id": runbook["source_id"],
                        "start_codepoint": 0,
                        "end_codepoint": len(text),
                        "quote": text,
                    },
                    "applicability": "requires_current_environment_and_admin_review",
                    "impact": "not_established_by_this_draft",
                    "execution": "reference_only_no_automatic_execution",
                }
            ]
        return {
            "schema_version": "operations_support_draft_v1",
            "source_id": source["source_id"],
            "source_sha256": digest(source),
            "objective": selection["objective"],
            "status": "unverified_operations_draft",
            "environment_status": "not_observed_by_this_task",
            "compatibility_status": "not_verified_from_reviewed_text",
            "observations": [
                {
                    "title": "模拟原文核对",
                    "explanation": SIMULATION_NOTE,
                    "evidence": [reference],
                }
            ],
            "hypotheses": [],
            "manual_checks": checks,
            "gaps": []
            if runbook
            else [
                {
                    "kind": "missing_reviewed_runbook",
                    "explanation": "未提供已审核运行手册。",
                }
            ],
        }
    if feature == "clinical_training":
        source = value["source"]
        question = source["feedback"]["questions"][0]
        raw = question["reviewed_rationale"][:1000]
        return {
            "schema_version": "clinical_training_feedback_draft_v1",
            "source_id": source["source_id"],
            "source_sha256": digest(source),
            "feedback_sha256": digest(source["feedback"]),
            "objective": "explain_practice_feedback",
            "status": "education_feedback_draft",
            "grade_policy": "server_score_unchanged",
            "explanations": [
                {
                    "question_id": question["question_id"],
                    "explanation": SIMULATION_NOTE,
                    "evidence": [
                        {
                            "target": "reviewed_rationale",
                            "question_id": question["question_id"],
                            "document_id": None,
                            "start_codepoint": 0,
                            "end_codepoint": len(raw),
                            "quote": raw,
                        }
                    ],
                }
            ],
            "revision_steps": [],
            "gaps": [],
        }
    evidence = value.get("evidence", [])
    ids = [
        row["source_id"]
        for row in evidence
        if isinstance(row, dict) and isinstance(row.get("source_id"), str)
    ]
    return {
        "summary": SIMULATION_NOTE,
        "sections": [
            {
                "title": "合成资料核对",
                "content": "仅整理本次已提供资料；缺项须按原记录核对，未生成诊断或治疗结论。",
                "source_ids": ids,
            }
        ],
        "warnings": [SIMULATION_NOTE],
        "missing_data": ["模拟服务不能验证医学正确性、真实模型表现或实际业务完整性。"],
    }


class SimulatorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, key, *, fail_first=0, failure="503"):
        if not ipaddress.ip_address(address[0]).is_loopback:
            raise ValueError("Simulator must bind to a loopback address")
        if not isinstance(key, str) or len(key) < 24:
            raise ValueError(
                "An explicit test key of at least24 characters is required"
            )
        if not 0 <= fail_first <= 10 or failure not in {"429", "503", "disconnect"}:
            raise ValueError("Fault injection must be bounded")
        self.key, self.fail_first, self.failure = key, fail_first, failure
        self.counts = defaultdict(
            lambda: {"attempts": 0, "injected_failures": 0, "successes": 0}
        )
        self.lock = threading.Lock()
        super().__init__(address, SimulatorHandler)


class SimulatorHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass  # Do not log request bodies, headers or test credentials.

    def send_json(self, status, value):
        body = canonical(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-HOIM-Simulated", "true")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        value = self.headers.get("Authorization", "")
        if not hmac.compare_digest(value, "Bearer " + self.server.key):
            self.close_connection = True
            self.send_json(
                401,
                {"error": "explicit simulator test key required", "simulated": True},
            )
            return False
        return True

    def do_GET(self):
        if self.path in {"/health/ready", "/health/live"}:
            self.send_json(
                200,
                {
                    "ready": True,
                    "simulated": True,
                    "model_inference": False,
                    "synthetic_data_only": True,
                },
            )
        elif self.path == "/_simulator/stats":
            if not self.authorized():
                return
            with self.server.lock:
                counts = {key: dict(value) for key, value in self.server.counts.items()}
            self.send_json(200, {"simulated": True, "models": counts})
        else:
            self.send_json(
                404, {"error": "unknown simulator endpoint", "simulated": True}
            )

    def do_POST(self):
        if not self.authorized():
            return
        if self.path not in {"/v1/chat/completions", "/v1/responses"}:
            self.close_connection = True
            self.send_json(
                404, {"error": "unknown simulator endpoint", "simulated": True}
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES:
                raise ValueError("Complete synthetic request must fit8MiB")
            packet = json.loads(self.rfile.read(length))
            model = packet["model"]
            if not isinstance(model, str) or not re.fullmatch(
                r"hoim-simulator:[a-z][a-z0-9_]{0,63}", model
            ):
                raise ValueError("Explicit hoim-simulator:<feature_key> model required")
            if model.removeprefix(MODEL_PREFIX) not in SUPPORTED_FEATURES:
                raise ValueError("Unknown simulator feature")
            with self.server.lock:
                counts = self.server.counts[model]
                counts["attempts"] += 1
                fail = counts["attempts"] <= self.server.fail_first
                if fail:
                    counts["injected_failures"] += 1
            if fail:
                if self.server.failure == "disconnect":
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                else:
                    self.send_json(
                        int(self.server.failure),
                        {
                            "error": {
                                "message": "injected synthetic simulator failure",
                                "type": "simulated_transient_error",
                            },
                            "simulated": True,
                        },
                    )
                return
            draft = draft_for(model.removeprefix(MODEL_PREFIX), public_input(packet))
            content = canonical(draft)
            envelope = {
                "id": "hoim-simulated-response",
                "model": model,
                "simulated": True,
            }
            # No tokenized inference occurs. Any zero usage below belongs only
            # to this explicitly simulated provider, never to a real model.
            if self.path.endswith("chat/completions"):
                envelope["choices"] = [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ]
            else:
                envelope.update(
                    status="completed",
                    output=[
                        {
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [{"type": "output_text", "text": content}],
                        }
                    ],
                )
            # Some older native contracts require complete nonnegative usage.
            # Zero explicitly represents no inference; it is simulator metadata.
            envelope["usage"] = (
                {"prompt_tokens": 0, "completion_tokens": 0}
                if self.path.endswith("chat/completions")
                else {"input_tokens": 0, "output_tokens": 0}
            )
            with self.server.lock:
                counts["successes"] += 1
            self.send_json(200, envelope)
        except (ValueError, KeyError, TypeError, IndexError):
            self.close_connection = True
            self.send_json(
                422,
                {
                    "error": "synthetic request cannot form a source-bound fixture",
                    "simulated": True,
                },
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--fail-first", type=int, default=0)
    parser.add_argument(
        "--failure", choices=["429", "503", "disconnect"], default="503"
    )
    args = parser.parse_args()
    server = SimulatorServer(
        (args.host, args.port),
        args.key_file.read_text().strip(),
        fail_first=args.fail_first,
        failure=args.failure,
    )
    print(
        canonical(
            {
                "endpoint": f"http://127.0.0.1:{server.server_port}/v1",
                "simulated": True,
                "model_inference": False,
            }
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
