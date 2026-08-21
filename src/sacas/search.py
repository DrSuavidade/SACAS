from __future__ import annotations

import json
from pathlib import Path
import re
import hashlib
from sacas.budget import estimate_tokens
from sacas.io import iter_repo_text_files

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
        from sacas.paths import sacas_generated_exclusions

        current_paths = set()
        for source in iter_repo_text_files(
            self.repository_root,
            excluded_roots=sacas_generated_exclusions(self.repository_root, self.sacas_root),
        ):
            rel_str = source.path
            current_paths.add(rel_str)
            content = source.content
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            cached = self.entries.get(rel_str)
            if cached and cached.get("content_hash") == content_hash:
                continue

            # Extract symbols simple heuristic
            symbols = []
            # match def, class, function, etc.
            matches = re.findall(r"\b(class|def|fn|struct|interface|function)\b\s+(\w+)", content)
            for m in matches:
                symbols.append(m[1])
                
            # Language
            suffix = Path(rel_str).suffix.lower()
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
                "content_hash": content_hash,
                "size": len(content.encode("utf-8")),
                "path": rel_str,
                "tokens": estimate_tokens(content),
                "filename_tokens": estimate_tokens(Path(rel_str).name),
                "directory_tokens": estimate_tokens(str(Path(rel_str).parent)),
                "symbols": list(dict.fromkeys(symbols)),
                "test_indicator": "test" in Path(rel_str).name.lower() or "test" in str(Path(rel_str).parent).lower(),
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
