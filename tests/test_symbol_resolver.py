from __future__ import annotations

from pathlib import Path
from sacas.regions import SymbolRangeResolver, find_python_ast_symbol_range, find_heuristic_symbol_line
from sacas.init import initialize
from sacas.paths import discover_manifest

def test_ast_symbol_range_parser() -> None:
    code = """def login(username, password):
    print("logging in")
    return True

class Session:
    def __init__(self):
        self.active = False
"""
    # ast exact range
    r_func = find_python_ast_symbol_range(code, "login")
    assert r_func == (1, 3)
    
    r_class = find_python_ast_symbol_range(code, "Session")
    assert r_class == (5, 7)

def test_heuristic_symbol_range() -> None:
    code = """
interface User {
    name: string;
}

const restore_session = () => {
    return true;
}
"""
    # Heuristics finding start lines
    line_user = find_heuristic_symbol_line(code, "User", "auth.ts")
    assert line_user == 2
    
    line_restore = find_heuristic_symbol_line(code, "restore_session", "auth.ts")
    assert line_restore == 6

def test_symbol_resolver(tmp_path: Path) -> None:
    init_result = initialize(tmp_path)
    installation = discover_manifest(tmp_path)
    
    auth_file = tmp_path / "src" / "auth.py"
    auth_file.parent.mkdir(exist_ok=True)
    auth_file.write_text("""def login():
    pass
""", encoding="utf-8")

    # Resolve python AST
    res = SymbolRangeResolver.resolve(installation, "src/auth.py", "login")
    assert res is not None
    assert res.start_line == 1
    assert res.end_line == 2
    assert res.source == "parser"
    assert res.confidence == 1.0
