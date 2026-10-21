"""Completed text-provider replies with exact, noninvented usage receipts.

Only one completed assistant text is accepted. Provider metadata is not a tool
authorization; tool/action/refusal/incomplete output is rejected. A known token
count is retained independently when its companion count is absent or invalid.
"""

from app.ai.charge_reconciliation_draft import MAX_BYTES, parse_draft, validate_draft


def utf8(value):
    return value.encode("utf-8", errors="strict")


MAX_USAGE_TOKENS = 2000000
ACTION_FIELDS = ("tool_calls", "function_call", "function_calls", "required_action", "actions")


class ChargeReplyError(ValueError):
    """Keep an actual usage receipt when the returned draft is rejected."""

    def __init__(self, counts=None):
        super().__init__("The provider did not return a complete recorded-ledger question draft")
        self.input_tokens, self.output_tokens = counts if counts is not None else (None, None)


def parse_provider_draft(kind, value, source, projection_hash):
    counts = None
    try:
        if not isinstance(value, dict) or kind not in {"chat", "responses"}:
            raise ValueError("A configured text-provider envelope is required")
        usage = value.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("Original usage is required")
        names = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
        receipt = tuple(usage.get(key) for key in names)
        counts = tuple(number if type(number) is int and 0 <= number <= MAX_USAGE_TOKENS else None for number in receipt)
        if any(number is None for number in counts):
            raise ValueError("The actual nonnegative token counts must be explicit integers")
        if "total_tokens" in usage and (type(usage["total_tokens"]) is not int or usage["total_tokens"] != sum(counts)):
            raise ValueError("An optional total token receipt must be an actual consistent integer")
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
                if len(part["text"]) > MAX_BYTES:
                    raise ValueError("Complete assistant text exceeds the complete recorded-ledger draft byte limit")
                total += len(utf8(part["text"]))
                if total > MAX_BYTES:
                    raise ValueError("Complete assistant text exceeds the complete recorded-ledger draft byte limit")
            raw = "".join(part["text"] for part in content)
        return validate_draft(source, parse_draft(raw), projection_hash), *counts
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise ChargeReplyError(counts) from exc
