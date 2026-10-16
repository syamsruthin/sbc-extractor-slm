"""The student model's prompt format, shared by training, evaluation and serving.

Training and serving MUST format requests identically (docs/01-foundations.md), so
this is the only place the student prompt is defined. Unlike the teacher prompt it
has no guidelines and no JSON schema: the fine-tuned model learns both from the
examples, which saves ~2.5k prompt tokens per request. At serving time, vLLM's
guided decoding enforces the schema.
"""

STUDENT_SYSTEM_PROMPT = (
    "Extract the plan details from this Summary of Benefits and Coverage (SBC) "
    "as minified JSON."
)


def build_messages(markdown: str, label_json: str | None = None) -> list[dict]:
    """Chat messages for one SBC; include label_json to make a training example."""
    messages = [
        {"role": "system", "content": STUDENT_SYSTEM_PROMPT},
        {"role": "user", "content": markdown},
    ]
    if label_json is not None:
        messages.append({"role": "assistant", "content": label_json})
    return messages
