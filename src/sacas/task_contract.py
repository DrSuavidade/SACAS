from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from sacas.io import write_json_atomic

TASK_CONTRACT_SCHEMA_VERSION = 1


class CanonicalStateError(ValueError):
    """An existing canonical state artifact cannot be trusted or decoded."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path.name} {reason}")

@dataclass(frozen=True, slots=True)
class TaskContract:
    schema_version: int
    task_id: str
    goal: str
    category: str
    criteria: tuple[str, ...]
    constraints: tuple[str, ...]
    verification: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "goal": self.goal,
            "category": self.category,
            "criteria": list(self.criteria),
            "constraints": list(self.constraints),
            "verification": list(self.verification),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskContract:
        if not isinstance(data, dict):
            raise ValueError("must contain a JSON object")
        schema_version = data.get("schema_version", TASK_CONTRACT_SCHEMA_VERSION)
        if schema_version != TASK_CONTRACT_SCHEMA_VERSION:
            raise ValueError("has unsupported schema version")
        for field in ("task_id", "goal", "category"):
            if not isinstance(data.get(field), str):
                raise ValueError(f"has invalid field '{field}'")
        for field in ("criteria", "constraints", "verification"):
            value = data.get(field, ())
            if field in data and (not isinstance(value, list) or not all(isinstance(item, str) for item in value)):
                raise ValueError(f"has invalid field '{field}'")
        return cls(
            schema_version=schema_version,
            task_id=data["task_id"],
            goal=data["goal"],
            category=data["category"],
            criteria=tuple(data.get("criteria", ())),
            constraints=tuple(data.get("constraints", ())),
            verification=tuple(data.get("verification", ())),
        )


def save_task_contract(task_dir: Path, contract: TaskContract) -> None:
    write_json_atomic(task_dir / "task.json", contract.to_dict())


def load_task_contract(task_dir: Path) -> TaskContract | None:
    path = task_dir / "task.json"
    if not path.exists():
        return None
    if not path.is_file():
        raise CanonicalStateError(path, "is not a regular file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CanonicalStateError(path, "is malformed") from error
    try:
        return TaskContract.from_dict(data)
    except (KeyError, TypeError, ValueError) as error:
        reason = str(error)
        if reason.startswith("has "):
            raise CanonicalStateError(path, reason) from error
        raise CanonicalStateError(path, "is malformed") from error


def task_contract_hash(contract: TaskContract) -> str:
    serialized = json.dumps(contract.to_dict(), sort_keys=True)
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"
