"""Complete text-provider reply parsing before literal coding-draft checks."""

from app.ai.coding_evidence_contract import parse_draft


def parse_provider_draft(kind, value):
    if not isinstance(value, dict):
        raise ValueError("Provider envelope must be an object")
    usage = value.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("Original usage receipt is required")
    if kind == "chat":
        choices = value.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("Exactly one completed coding draft is required")
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError("A typed assistant message is required")
        message = choice["message"]
        if choice.get("finish_reason") != "stop" or message.get("refusal") or message.get("role") != "assistant":
            raise ValueError("Incomplete or refused coding draft")
        text = message["content"]
        names = ("prompt_tokens", "completion_tokens")
    elif kind == "responses":
        if value.get("status") != "completed":
            raise ValueError("Incomplete coding draft")
        output = value.get("output")
        if not isinstance(output, list) or any(not isinstance(item, dict) or item.get("type") not in {"reasoning", "message"} for item in output):
            raise ValueError("Unexpected provider action in coding draft")
        messages = [item for item in output if item.get("type") == "message"]
        if len(messages) != 1 or messages[0].get("role") != "assistant":
            raise ValueError("Exactly one assistant draft is required")
        content = messages[0].get("content")
        if not isinstance(content, list) or not content or any(not isinstance(part, dict) or part.get("type") != "output_text" or type(part.get("text")) is not str for part in content):
            raise ValueError("Refusal or non-text provider result")
        text = "".join(part["text"] for part in content)
        names = ("input_tokens", "output_tokens")
    else:
        raise ValueError("Coding evidence requires a configured text provider")
    counts = tuple(usage.get(key) for key in names)
    if any(type(number) is not int or not 0 <= number <= 2000000 for number in counts):
        raise ValueError("Exact nonnegative original token counts are required")
    return parse_draft(text), *counts
