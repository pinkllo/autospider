from __future__ import annotations

import json

from . import contract_tmp_dir, run_contract_pipeline, snapshot_shape


def test_redis_key_prefixes_and_payload_shapes_match_contract_snapshot() -> None:
    with contract_tmp_dir() as tmp_path:
        artifacts = run_contract_pipeline(tmp_path)
        client = artifacts.redis_client
        execution_id = artifacts.execution_id
        key_prefix = f"autospider:urls:run:{execution_id}"
        snapshot = {
            _normalize_key(
                f"autospider:task_progress:{execution_id}",
                execution_id,
            ): _hash_snapshot(client.hgetall(f"autospider:task_progress:{execution_id}")),
            _normalize_key(f"{key_prefix}:data", execution_id): _data_hash_snapshot(
                client.hgetall(f"{key_prefix}:data")
            ),
            _normalize_key(f"{key_prefix}:stream", execution_id): _stream_snapshot(
                client.xrange(f"{key_prefix}:stream")
            ),
        }

        assert snapshot == {
            "autospider:task_progress:<execution_id>": {
                "redis_type": "hash",
                "fields": {
                    "completed": "str",
                    "current_url": "str",
                    "execution_id": "str",
                    "failed": "str",
                    "payload": {
                        "completed": "int",
                        "current_url": "str",
                        "execution_id": "str",
                        "failed": "int",
                        "finished_at": "int",
                        "pending_count": "int",
                        "progress": "str",
                        "resume_mode": "str",
                        "runtime_state": {
                            "queue": {"pending_count": "int", "stream_length": "int"},
                            "resume_mode": "str",
                            "stage": "str",
                            "thread_id": "str",
                        },
                        "stage": "str",
                        "status": "str",
                        "stream_length": "int",
                        "thread_id": "str",
                        "total": "int",
                        "updated_at": "int",
                    },
                    "progress": "str",
                    "pending_count": "str",
                    "resume_mode": "str",
                    "runtime_state": {
                        "queue": {"pending_count": "int", "stream_length": "int"},
                        "resume_mode": "str",
                        "stage": "str",
                        "thread_id": "str",
                    },
                    "stage": "str",
                    "status": "str",
                    "stream_length": "str",
                    "thread_id": "str",
                    "total": "str",
                    "finished_at": "str",
                    "updated_at": "str",
                },
            },
            "autospider:urls:run:<execution_id>:data": {
                "redis_type": "hash",
                "fields": {
                    "detail-001": {
                        "created_at": "int",
                        "metadata": {"source": "str"},
                        "url": "str",
                    }
                },
            },
            "autospider:urls:run:<execution_id>:stream": {
                "redis_type": "stream",
                "entries": [{"data_id": "str"}],
            },
        }


def _normalize_key(key: str, execution_id: str) -> str:
    return key.replace(execution_id, "<execution_id>")


def _hash_snapshot(payload: dict[str, str]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key, value in payload.items():
        if key in {"payload", "runtime_state"}:
            fields[key] = snapshot_shape(json.loads(value))
            continue
        fields[key] = type(value).__name__
    return {"redis_type": "hash", "fields": fields}


def _data_hash_snapshot(payload: dict[str, str]) -> dict[str, object]:
    parsed = {key: snapshot_shape(json.loads(value)) for key, value in payload.items()}
    return {"redis_type": "hash", "fields": parsed}


def _stream_snapshot(entries: list[tuple[str, dict[str, str]]]) -> dict[str, object]:
    normalized = [snapshot_shape(dict(fields)) for _, fields in entries]
    return {"redis_type": "stream", "entries": normalized}
