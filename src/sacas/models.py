"""Versioned, immutable data models for SACAS machine state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


SCHEMA_VERSION = 1
GRAPHIFY_MODES = frozenset({"off", "existing", "code-only", "semantic"})


class SchemaVersionError(ValueError):
    """Raised when a manifest cannot be interpreted by this SACAS version."""


@dataclass(frozen=True, slots=True)
class Manifest:
    """The canonical, versioned installation marker stored as JSON."""

    repository_root: str = "."
    sacas_root: str = "Structure"
    graphify_mode: str = "off"
    graphify_output: str = "graphify-out"
    adapters: tuple[str, ...] = ()
    context_budget: int = 12_000
    current_task_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapters", tuple(self.adapters))
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Unsupported SACAS schema version {self.schema_version}; "
                f"expected {SCHEMA_VERSION}."
            )
        if self.graphify_mode not in GRAPHIFY_MODES:
            valid_modes = ", ".join(sorted(GRAPHIFY_MODES))
            raise ValueError(f"graphify_mode must be one of: {valid_modes}")
        if self.context_budget <= 0:
            raise ValueError("context_budget must be positive")
        if not all(isinstance(adapter, str) and adapter for adapter in self.adapters):
            raise ValueError("adapters must contain non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible data with stable collection types."""
        return {
            "schema_version": self.schema_version,
            "repository_root": self.repository_root,
            "sacas_root": self.sacas_root,
            "graphify_mode": self.graphify_mode,
            "graphify_output": self.graphify_output,
            "adapters": list(self.adapters),
            "context_budget": self.context_budget,
            "current_task_id": self.current_task_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Manifest":
        """Load and validate the current manifest schema."""
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Unsupported SACAS schema version {version!r}; expected {SCHEMA_VERSION}."
            )
        adapters = data.get("adapters", ())
        if not isinstance(adapters, list) or not all(isinstance(item, str) for item in adapters):
            raise ValueError("adapters must be a JSON array of strings")
        return cls(
            schema_version=version,
            repository_root=_required_string(data, "repository_root", "."),
            sacas_root=_required_string(data, "sacas_root", "Structure"),
            graphify_mode=_required_string(data, "graphify_mode", "off"),
            graphify_output=_required_string(data, "graphify_output", "graphify-out"),
            adapters=tuple(adapters),
            context_budget=_positive_integer(data, "context_budget", 12_000),
            current_task_id=_optional_string(data, "current_task_id"),
        )


def _required_string(data: Mapping[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_string(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def _positive_integer(data: Mapping[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value
