from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sacas.active_context import ActiveContextManifest
    from sacas.paths import Installation

class ContextEnforcementProvider:
    def enforce(self, installation: Installation, manifest: ActiveContextManifest) -> None:
        raise NotImplementedError

class AdvisoryEnforcementProvider(ContextEnforcementProvider):
    def enforce(self, installation: Installation, manifest: ActiveContextManifest) -> None:
        # Advisory: only write a report or print a warning (we do nothing since it's just advisory)
        pass

class CursorEnforcementProvider(ContextEnforcementProvider):
    def enforce(self, installation: Installation, manifest: ActiveContextManifest) -> None:
        from sacas.active_context import enforce_cursor_negation_patterns
        enforce_cursor_negation_patterns(installation, manifest)
