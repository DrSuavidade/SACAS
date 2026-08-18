from __future__ import annotations

from pathlib import Path
from sacas.graphify import GraphifyProvider, GraphifyQueryResult

class FakeGraphifyProvider(GraphifyProvider):
    def __init__(self, capable: bool = True, mock_paths: tuple[str, ...] = ()):
        self.capable = capable
        self.mock_paths = mock_paths
        self.queries_received = []

    def verify_capabilities(self, required: list[str]) -> bool:
        return self.capable

    def query(self, goal: str, graph_path: Path) -> GraphifyQueryResult | None:
        self.queries_received.append((goal, graph_path))
        if not self.capable:
            return None
        return GraphifyQueryResult(
            raw_output="Fake Graphify output",
            paths=self.mock_paths,
            status="success"
        )
