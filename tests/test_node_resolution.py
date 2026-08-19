from __future__ import annotations

import json
from pathlib import Path
import pytest

from sacas.regions import find_python_ast_symbol_at_line, SymbolRangeResolver
from sacas.init import initialize
from sacas.paths import discover_manifest

def test_find_python_ast_symbol_at_line() -> None:
    code = (
        "class Helper:\n"
        "    def method(self):\n"
        "        pass\n"
        "\n"
        "def func():\n"
        "    pass\n"
    )
    res = find_python_ast_symbol_at_line(code, 2)
    assert res is not None
    assert res[0] == "method"
    assert res[1] == 2
    assert res[2] == 3

    res_class = find_python_ast_symbol_at_line(code, 1)
    assert res_class is not None
    assert res_class[0] == "Helper"
    assert res_class[1] == 1
    assert res_class[2] == 3

def test_resolve_node_range(tmp_path: Path) -> None:
    initialize(tmp_path)
    installation = discover_manifest(tmp_path)

    # Write helper file
    app_py = tmp_path / "src" / "app.py"
    app_py.parent.mkdir(exist_ok=True, parents=True)
    app_py.write_text(
        "def main_func():\n"
        "    print('main')\n",
        encoding="utf-8"
    )

    res = SymbolRangeResolver.resolve_node_range(
        installation,
        "src/app.py",
        node_label="main_func",
        node_line=1
    )
    assert res is not None
    selection, reason = res
    assert selection["mode"] == "symbols"
    symbols = selection["symbols"]
    assert len(symbols) == 1
    assert symbols[0].name == "main_func"
    assert symbols[0].range.start_line == 1
    assert symbols[0].range.end_line == 2


def test_normalize_selections() -> None:
    from sacas.regions import normalize_selections
    from sacas.active_context import ActiveSymbolContext, SourceRange

    syms = (
        ActiveSymbolContext(name="A", range=SourceRange(84, 130, "parser", 1.0), reason="R1"),
        ActiveSymbolContext(name="B", range=SourceRange(110, 180, "parser", 1.0), reason="R2"),
        ActiveSymbolContext(name="C", range=SourceRange(177, 210, "parser", 1.0), reason="R3"),
        ActiveSymbolContext(name="D", range=SourceRange(300, 350, "parser", 1.0), reason="R4"),
    )

    merged = normalize_selections(syms)
    assert len(merged) == 2
    # First merged symbol: A, B, C range: 84 - 210
    assert merged[0].name == "A, B, C"
    assert merged[0].range.start_line == 84
    assert merged[0].range.end_line == 210
    # Second merged symbol: D range: 300 - 350
    assert merged[1].name == "D"
    assert merged[1].range.start_line == 300
    assert merged[1].range.end_line == 350

