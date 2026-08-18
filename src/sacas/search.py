from __future__ import annotations

import json
from pathlib import Path
import re
import hashlib
from sacas.budget import estimate_tokens

class FallbackIndex:
    def __init__(self, repository_root: Path, sacas_root: Path):
        self.repository_root = repository_root
        self.sacas_root = sacas_root
        self.index_path = sacas_root / ".sacas" / "fallback_index.json"
        self.entries: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if self.index_path.is_file():
            try:
                self.entries = json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                self.entries = {}

    def save(self) -> None:
        from sacas.io import stable_json, write_text_atomic
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(self.index_path, stable_json(self.entries))

    def update(self) -> None:
        """Scan repository and update changed/new files in the index."""
        ignored_parts = {".git", ".sacas", "__pycache__", "Structure", "graphify-out", ".worktrees"}
        
        # Scan repo files
        current_paths = set()
        for path in self.repository_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.repository_root)
            if any(part in ignored_parts for part in relative.parts):
                continue
                
            rel_str = relative.as_posix()
            current_paths.add(rel_str)
            
            try:
                stat = path.stat()
                mtime_ns = stat.st_mtime_ns
                size = stat.st_size
            except OSError:
                continue
                
            cached = self.entries.get(rel_str)
            if cached and cached.get("mtime_ns") == mtime_ns and cached.get("size") == size:
                continue
                
            # File changed or new - parse and index it
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                content = ""
                
            # Extract symbols simple heuristic
            symbols = []
            # match def, class, function, etc.
            matches = re.findall(r"\b(class|def|fn|struct|interface|function)\b\s+(\w+)", content)
            for m in matches:
                symbols.append(m[1])
                
            # Language
            suffix = path.suffix.lower()
            if suffix == ".py":
                lang = "python"
            elif suffix in (".js", ".ts", ".jsx", ".tsx"):
                lang = "javascript"
            elif suffix == ".rs":
                lang = "rust"
            elif suffix == ".go":
                lang = "go"
            else:
                lang = "unknown"
                
            self.entries[rel_str] = {
                "mtime_ns": mtime_ns,
                "size": size,
                "path": rel_str,
                "tokens": estimate_tokens(content),
                "filename_tokens": estimate_tokens(path.name),
                "directory_tokens": estimate_tokens(str(relative.parent)),
                "symbols": list(dict.fromkeys(symbols)),
                "test_indicator": "test" in path.name.lower() or "test" in str(relative.parent).lower(),
                "language": lang
            }
            
        # Clean up deleted files from index
        for path_str in list(self.entries.keys()):
            if path_str not in current_paths:
                del self.entries[path_str]
                
        self.save()

    def search(self, goal: str) -> list[dict]:
        """Perform lexical scoring against indexed files and return top matches."""
        from sacas.tasks import extract_keywords
        keywords = extract_keywords(goal)
        if not keywords:
            return []
            
        scored = []
        for path_str, entry in self.entries.items():
            score = 0
            filename = Path(path_str).name.lower()
            matched = []
            
            # Check filename keywords
            for kw in keywords:
                if kw in filename:
                    score += 4
                    matched.append(kw)
                    if filename.startswith(kw):
                        score += 2
                        
            # Check directory keywords
            for comp in Path(path_str).parent.parts:
                for kw in keywords:
                    if kw in comp.lower():
                        score += 3
                        if kw not in matched:
                            matched.append(kw)
                            
            # Check symbols keywords
            for sym in entry.get("symbols", []):
                for kw in keywords:
                    if kw in sym.lower():
                        score += 5
                        if kw not in matched:
                            matched.append(kw)
                            
            if score > 0:
                scored.append((score, path_str, matched))
                
        scored.sort(key=lambda s: (-s[0], len(s[1]), s[1]))
        return scored
