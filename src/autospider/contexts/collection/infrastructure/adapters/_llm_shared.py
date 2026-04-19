from __future__ import annotations


def get_model_name(llm: object) -> str | None:
    return getattr(llm, "model_name", None) or getattr(llm, "model", None)


def build_trace_payload(
    *,
    llm: object,
    input_payload: dict[str, object],
    raw_response: str,
    response_summary: dict[str, object],
    parsed_payload: dict | None = None,
    error: Exception | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": get_model_name(llm),
        "input": input_payload,
        "output": {
            "raw_response": raw_response,
            "parsed_payload": parsed_payload,
        },
        "response_summary": response_summary,
    }
    if error is not None:
        payload["error"] = error
    return payload
