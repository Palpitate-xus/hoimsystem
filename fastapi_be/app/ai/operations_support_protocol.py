"""Whole reviewed operations model input; pure citation/shape checks, no authority."""

import hashlib

from app.ai import operations_support_contract as c
from app.ai import operations_support_projection as projection
from app.ai.operations_support_task_contract import OperationsDraft, OperationsTaskSelection, verify_result
from app.ai.operations_support_task_prompt import OBJECTIVES, PROMPT_VERSION, SYSTEM_PROMPT, TASK_PROMPT

MAX_BYTES = c.MAX_WHOLE_BYTES


def instructions_for(task):
    if type(task) is not str or not task.strip() or len(task.encode("utf-8")) > 65535:
        raise ValueError("The entire nonempty original Task must fit 65535 UTF8 bytes")
    return SYSTEM_PROMPT + "\n\n" + task


def model_wire(source, selection, task_prompt=TASK_PROMPT):
    source = projection.OperationsSupportSource.model_validate(projection._value(source), strict=True)
    selection = OperationsTaskSelection.model_validate(selection, strict=True)
    if selection.operations_case_id != source.source_id:
        raise ValueError("The selected finite case must equal this full reviewed public source")
    instructions = instructions_for(task_prompt)
    wire = {
        "instructions": instructions,
        "input": {
            "schema_version": "operations_support_model_input_v1",
            "native_task_version": PROMPT_VERSION,
            "selection": selection.model_dump(mode="json"),
            "objective_description": OBJECTIVES[selection.objective],
            "source": source.model_dump(mode="json"),
        },
        "response_schema": OperationsDraft.model_json_schema(),
    }
    if len(c.canonical_json(wire).encode("utf-8")) > MAX_BYTES:
        raise ValueError("The entire public source, fixed System, Task and schema exceed 8MiB; no clipping")
    return wire, hashlib.sha256(instructions.encode("utf-8")).hexdigest()


def parse_draft(raw, source, selection):
    return verify_result(raw, source, selection)
