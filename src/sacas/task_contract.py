from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from sacas.io import write_json_atomic

TASK_CONTRACT_SCHEMA_VERSION = 1

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
        return cls(
            schema_version=data.get("schema_version", TASK_CONTRACT_SCHEMA_VERSION),
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
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TaskContract.from_dict(data)
    except Exception:
        return None


def task_contract_hash(contract: TaskContract) -> str:
    serialized = json.dumps(contract.to_dict(), sort_keys=True)
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"
