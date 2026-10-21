"""Whole educational model wire; source structure never grants SQL authority."""

import hashlib

from app.ai import clinical_training_contract as c
from app.ai.clinical_training_task_contract import OBJECTIVES, TrainingFeedbackDraft, TrainingFeedbackSource, TrainingTaskSelection, verify_draft
from app.ai.clinical_training_task_prompt import PROMPT_VERSION, SYSTEM_PROMPT, TASK_PROMPT

MAX_BYTES = c.WHOLE_BYTES


def instructions_for(task):
    if type(task) is not str or not task or len(task.encode("utf-8", errors="strict")) > 65535:
        raise ValueError("The complete nonempty Task must fit actual TEXT bytes")
    return SYSTEM_PROMPT + "\n\n" + task


def model_wire(source, selection, task_prompt=TASK_PROMPT):
    source = TrainingFeedbackSource.model_validate(c.parse_packet(source), strict=True)
    selection = TrainingTaskSelection.model_validate(c.parse_packet(selection), strict=True)
    if selection.clinical_training_submission_id != source.source_id:
        raise ValueError("The selected actual practice must equal the complete Source")
    instructions = instructions_for(task_prompt)
    wire = dict(
        instructions=instructions,
        input=dict(schema_version="clinical_training_model_input_v1", native_task_version=PROMPT_VERSION, selection=selection.model_dump(mode="json"), objective_description=OBJECTIVES[selection.objective], source=source.model_dump(mode="json")),
        response_schema=TrainingFeedbackDraft.model_json_schema(),
    )
    if len(c.canonical_json(wire).encode("utf-8")) > MAX_BYTES:
        raise ValueError("The complete Source, System, Task and response schema exceed8MiB; no clipping")
    return wire, hashlib.sha256(instructions.encode()).hexdigest()


def parse_draft(raw, source, selection):
    return verify_draft(raw, source, selection)
