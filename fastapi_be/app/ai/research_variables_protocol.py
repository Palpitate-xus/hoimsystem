"""Completed text-provider replies with exact, noninvented usage receipts.

Only one completed assistant text is accepted. Provider metadata is not a tool
authorization; tool/action/refusal/incomplete output is rejected. A known token
count is retained independently when its companion count is absent or invalid.
"""

from app.ai.research_variables_draft import parse_draft_json
from app.ai.research_variables_task_contract import MAX_WIRE_BYTES, VariableTaskSource, canonical, strict_json
from app.ai.research_variables_task_result import bind_draft

MAX_JSON_BYTES = MAX_WIRE_BYTES


def bounded_json(value):
    return strict_json(canonical(value))


def utf8(value):
    return value.encode("utf-8", errors="strict")


MAX_USAGE_TOKENS = 2000000
ACTION_FIELDS = ("tool_calls", "function_call", "function_calls", "required_action", "actions")


class VariableReplyError(ValueError):
    """Keep an actual usage receipt when the returned draft is rejected."""

    def __init__(self, counts=None):
        super().__init__("The provider did not return a complete literal research-variable hypothesis draft")
        self.input_tokens, self.output_tokens = counts if counts is not None else (None, None)


def parse_provider_draft(kind, value, source, instructions_digest):
    counts = (None, None)
    try:
        if not isinstance(value, dict) or kind not in {"chat", "responses"}:
            raise ValueError("A configured text-provider envelope is required")
        usage = value.get("usage")
        if usage is None:
            usage = {}
        if type(usage) is not dict:
            raise ValueError("Reported usage must be an object or remain absent/unknown")
        names = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
        receipt = tuple(usage.get(key) for key in names)
        counts = tuple(number if type(number) is int and 0 <= number <= MAX_USAGE_TOKENS else None for number in receipt)
        if any(original is not None and known is None for original, known in zip(receipt, counts, strict=True)):
            raise ValueError("An explicitly reported count must be an actual bounded integer; no coercion")
        if "total_tokens" in usage:
            total = usage["total_tokens"]
            if type(total) is not int or not 0 <= total <= 2 * MAX_USAGE_TOKENS or all(number is not None for number in counts) and total != sum(counts):
                raise ValueError("An optional total token receipt must be an actual consistent integer")
            if any(number is not None and total < number for number in counts):
                raise ValueError("A declared total cannot be less than an independently reported component")
            # A total never supplies a missing input/output component. Content
            # acceptance and knowledge of its billing counts are independent.
        bounded_json(value)
        if not isinstance(source, VariableTaskSource):
            raise ValueError("The complete server-built typed public Source is required")
        if value.get("refusal") is not None:
            raise ValueError("A refusal is not a literal draft")
        if value.get("error") is not None or value.get("incomplete_details") is not None or any(value.get(key) is not None for key in ACTION_FIELDS):
            raise ValueError("Provider error, incomplete output or external action is not a draft")
        if kind == "chat":
            choices = value.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ValueError("Exactly one completed assistant reply is required")
            choice = choices[0]
            message = choice.get("message")
            if any(choice.get(key) is not None for key in ACTION_FIELDS):
                raise ValueError("A provider action cannot accompany an assistant choice")
            if "index" in choice and (type(choice["index"]) is not int or choice["index"] != 0):
                raise ValueError("The sole configured choice must have index zero when indexed")
            if choice.get("finish_reason") != "stop" or not isinstance(message, dict) or message.get("role") != "assistant" or message.get("refusal") is not None:
                raise ValueError("Incomplete or refused assistant reply")
            if any(message.get(key) is not None for key in (*ACTION_FIELDS, "audio", "tool_call_id")):
                raise ValueError("A tool, function or audio output is not a text draft")
            raw = message.get("content")
            if type(raw) is not str:
                raise ValueError("The complete assistant text is required")
        else:
            output = value.get("output")
            if value.get("status") != "completed" or not isinstance(output, list) or any(not isinstance(item, dict) or item.get("type") not in {"reasoning", "message"} for item in output):
                raise ValueError("Incomplete reply or unexpected provider action")
            if any(item.get("type") == "reasoning" and item.get("status") not in {None, "completed"} for item in output):
                raise ValueError("Incomplete reasoning cannot accompany a completed draft")
            if any(any(item.get(key) is not None for key in ACTION_FIELDS) for item in output):
                raise ValueError("An action cannot be hidden inside another provider output type")
            messages = [item for item in output if item["type"] == "message"]
            if len(messages) != 1 or messages[0].get("role") != "assistant" or messages[0].get("status") != "completed":
                raise ValueError("Exactly one completed assistant message is required")
            if messages[0].get("refusal") is not None or any(messages[0].get(key) is not None for key in ACTION_FIELDS):
                raise ValueError("A refusal or action cannot accompany assistant text")
            content = messages[0].get("content")
            if (
                not isinstance(content, list)
                or not content
                or any(not isinstance(part, dict) or part.get("type") != "output_text" or type(part.get("text")) is not str or part.get("refusal") is not None for part in content)
            ):
                raise ValueError("Refused or nontext reply")
            total = 0
            for part in content:
                if any(part.get(key) is not None for key in ACTION_FIELDS):
                    raise ValueError("An action cannot accompany an output text part")
                if len(part["text"]) > MAX_JSON_BYTES:
                    raise ValueError("Complete assistant text exceeds the complete literal research-variable hypothesis draft byte limit")
                total += len(utf8(part["text"]))
                if total > MAX_JSON_BYTES:
                    raise ValueError("Complete assistant text exceeds the complete literal research-variable hypothesis draft byte limit")
            raw = "".join(part["text"] for part in content)
        strict_json(raw)
        draft = parse_draft_json(raw, [row.model_dump(mode="json") for row in source.documents])
        return bind_draft(draft, source, instructions_digest), *counts
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise VariableReplyError(counts) from exc
