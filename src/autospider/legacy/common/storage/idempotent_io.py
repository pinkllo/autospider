from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

DEFAULT_VOLATILE_KEYS = {
    "created_at",
    "updated_at",
    "timestamp",
    "last_updated",
}


def _normalize(value: Any, volatile_keys: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize(item, volatile_keys)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in volatile_keys
        }
    if isinstance(value, list):
        return [_normalize(item, volatile_keys) for item in value]
    return value


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def load_json_if_exists(path: str | Path) -> Any | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_text_if_changed(path: str | Path, text: str) -> bool:
    file_path = Path(path)
    if file_path.exists():
        try:
            if file_path.read_text(encoding="utf-8") == text:
                return False
        except Exception:
            pass
    _atomic_write_text(file_path, text)
    return True


def write_json_idempotent(
    path: str | Path,
    payload: Any,
    *,
    identity_keys: Iterable[str] = (),
    volatile_keys: set[str] | None = None,
) -> Any:
    file_path = Path(path)
    normalized_volatile = set(volatile_keys or DEFAULT_VOLATILE_KEYS)
    existing = load_json_if_exists(file_path)

    if isinstance(existing, dict) and isinstance(payload, dict):
        same_identity = True
        for key in identity_keys:
            if existing.get(key) != payload.get(key):
                same_identity = False
                break

        if same_identity and _normalize(existing, normalized_volatile) == _normalize(
            payload, normalized_volatile
        ):
            return existing

        if same_identity and "created_at" in existing and "created_at" in payload:
            payload = dict(payload)
            payload["created_at"] = existing.get("created_at")

    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    write_text_if_changed(file_path, text)
    return payload
