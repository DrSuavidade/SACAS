from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from sacas.active_context import ContextPolicyState

if TYPE_CHECKING:
    from sacas.active_context import ActiveContextManifest
    from sacas.paths import Installation

class ContextEnforcementProvider:
    def enforce(self, installation: Installation, manifest: ActiveContextManifest) -> None:
        raise NotImplementedError

class AdvisoryEnforcementProvider(ContextEnforcementProvider):
    def enforce(self, installation: Installation, manifest: ActiveContextManifest) -> None:
        # Advisory: only write a report or print a warning (we do nothing since it's just advisory/warn)
        pass

class CursorEnforcementProvider(ContextEnforcementProvider):
    def enforce(self, installation: Installation, manifest: ActiveContextManifest) -> None:
        from sacas.active_context import enforce_cursor_negation_patterns
        enforce_cursor_negation_patterns(installation, manifest)


def negotiate_policy(installation: Installation, requested: str) -> ContextPolicyState:
    if requested == "warn":
        return ContextPolicyState(
            requested="warn",
            effective="warn",
            provider="advisory",
            file_reads="warn",
            terminal_reads="advisory",
            mcp_reads="advisory"
        )
    elif requested == "enforce":
        adapters = getattr(installation.manifest, "adapters", ())
        if "cursor" in adapters:
            return ContextPolicyState(
                requested="enforce",
                effective="partial",
                provider="cursor",
                file_reads="partial",
                terminal_reads="advisory",
                mcp_reads="advisory"
            )
        else:
            return ContextPolicyState(
                requested="enforce",
                effective="advisory",
                provider="advisory",
                file_reads="advisory",
                terminal_reads="advisory",
                mcp_reads="advisory"
            )
    else:  # advisory
        return ContextPolicyState(
            requested="advisory",
            effective="advisory",
            provider="advisory",
            file_reads="advisory",
            terminal_reads="advisory",
            mcp_reads="advisory"
        )


def get_enforcement_provider(installation: Installation, manifest: ActiveContextManifest) -> ContextEnforcementProvider:
    provider_name = manifest.policy.provider if manifest.policy else "advisory"
    if provider_name == "cursor":
        return CursorEnforcementProvider()
    return AdvisoryEnforcementProvider()
