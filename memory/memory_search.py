#!/usr/bin/env python3
"""
memory_search.py - sidecar GA memory index/search helper.

MVP scope:
- No integration with ga.py/agentmain.py; run manually from CLI.
- Uses SQLite FTS5 if available, otherwise clear error.
- Reads approved memory layers and writes index DB outside memory/ by default: temp/memory_index.sqlite3.
- Skips secret-like filenames and hidden/cache folders.

Examples:
  python memory/memory_search.py rebuild
  python memory/memory_search.py search "历史决策"
  python memory/memory_search.py stats
  python memory/memory_search.py check
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys

# Keep CLI usable on Windows legacy consoles/pipes: preserve the active
# encoding, but escape characters it cannot represent (for example emoji in
# search snippets) instead of raising UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="backslashreplace")
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

TEXT_SUFFIXES = {".md", ".txt", ".py", ".json"}
SECRET_NAME_RE = re.compile(r"(secret|token|cookie|credential|password|passwd|api[_-]?key|apikey|claim|clm|\.env|keychain)", re.I)
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", "node_modules"}
MAX_FILE_BYTES = 2_000_000
DEFAULT_SNIPPET_CHARS = 220


@dataclass
class MemoryDoc:
    path: str
    layer: str
    title: str
    text: str
    size: int
    mtime: float


def repo_root_from_here() -> Path:
    # memory/memory_search.py -> repo root
    return Path(__file__).resolve().parents[1]


def default_db_path(root: Path) -> Path:
    return root / "temp" / "memory_index.sqlite3"


def has_fts5() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        conn.execute("INSERT INTO t(x) VALUES ('hello memory')")
        conn.execute("SELECT rowid FROM t WHERE t MATCH 'memory'").fetchall()
        conn.close()
        return True
    except sqlite3.Error:
        return False


def is_secret_like(path: Path) -> bool:
    return any(SECRET_NAME_RE.search(part) for part in path.parts)


def safe_read_text(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raw = raw[:MAX_FILE_BYTES]
    # utf-8 first; fallback keeps search usable without failing whole index.
    return raw.decode("utf-8", errors="replace")


def layer_for(path: Path, memory_dir: Path) -> str:
    try:
        rel = path.relative_to(memory_dir).as_posix()
    except ValueError:
        rel = path.as_posix()
    if rel == "global_mem_insight.txt":
        return "L1"
    if rel == "global_mem.txt":
        return "L2"
    if rel.startswith("daily_logs/"):
        return "L3.5"
    if rel.startswith("L4_raw_sessions/"):
        return "L4"
    if path.suffix.lower() in {".md", ".py"}:
        return "L3"
    return "memory"


def title_for(path: Path, text: str) -> str:
    for line in text.splitlines()[:40]:
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()[:160]
    return path.stem[:160]


def iter_memory_files(root: Path, include_l4: bool = True) -> Iterator[Path]:
    memory_dir = root / "memory"
    if not memory_dir.exists():
        return
    allow_exact = {memory_dir / "global_mem_insight.txt", memory_dir / "global_mem.txt"}
    # Root-level L3 files.
    for p in sorted(memory_dir.iterdir(), key=lambda x: x.as_posix().lower()):
        if p.name in SKIP_DIRS or p.name.startswith("."):
            continue
        if p.is_file():
            if p in allow_exact or p.suffix.lower() in TEXT_SUFFIXES:
                if not is_secret_like(p):
                    yield p
        elif p.is_dir():
            if p.name == "L4_raw_sessions" and not include_l4:
                continue
            # Include daily_logs, L4 summaries/scripts, and sub-SOP dirs; skip hidden/cache/secret-like.
            if is_secret_like(p):
                continue
            for sub in sorted(p.rglob("*"), key=lambda x: x.as_posix().lower()):
                if any(part in SKIP_DIRS or part.startswith(".") for part in sub.parts):
                    continue
                if sub.is_file() and sub.suffix.lower() in TEXT_SUFFIXES and not is_secret_like(sub):
                    yield sub


def collect_docs(root: Path, include_l4: bool = True) -> List[MemoryDoc]:
    root = root.resolve()
    memory_dir = root / "memory"
    docs: List[MemoryDoc] = []
    for path in iter_memory_files(root, include_l4=include_l4):
        try:
            st = path.stat()
            text = safe_read_text(path)
            rel = path.relative_to(root).as_posix()
            docs.append(MemoryDoc(
                path=rel,
                layer=layer_for(path, memory_dir),
                title=title_for(path, text),
                text=text,
                size=st.st_size,
                mtime=st.st_mtime,
            ))
        except (OSError, UnicodeError):
            # One unreadable file should not break the index.
            continue
    return docs


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS docs(path TEXT PRIMARY KEY, layer TEXT NOT NULL, title TEXT, size INTEGER, mtime REAL)")
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(path UNINDEXED, layer UNINDEXED, title, text)")
    conn.commit()


def rebuild(root: Path, db_path: Path, include_l4: bool = True) -> dict:
    if not has_fts5():
        raise SystemExit("SQLite FTS5 is not available in this Python build")
    docs = collect_docs(root, include_l4=include_l4)
    conn = connect(db_path)
    init_schema(conn)
    conn.execute("DELETE FROM docs")
    conn.execute("DELETE FROM docs_fts")
    for doc in docs:
        conn.execute(
            "INSERT INTO docs(path, layer, title, size, mtime) VALUES (?, ?, ?, ?, ?)",
            (doc.path, doc.layer, doc.title, doc.size, doc.mtime),
        )
        conn.execute(
            "INSERT INTO docs_fts(path, layer, title, text) VALUES (?, ?, ?, ?)",
            (doc.path, doc.layer, doc.title, doc.text),
        )
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('root', ?)", (str(root.resolve()),))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('include_l4', ?)", ("1" if include_l4 else "0",))
    conn.commit()
    counts = stats_from_conn(conn)
    conn.close()
    return {"db": str(db_path), "indexed": len(docs), "counts": counts}


def quote_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def build_match_query(query: str) -> str:
    # Prefer exact phrase for CJK/natural-language search; OR-token fallback for ascii words.
    q = query.strip()
    if not q:
        raise ValueError("empty query")
    ascii_terms = re.findall(r"[A-Za-z0-9_\-]{2,}", q)
    if ascii_terms and len("".join(ascii_terms)) >= max(2, len(q.replace(" ", "")) // 2):
        return " OR ".join(quote_fts_term(t) for t in ascii_terms[:8])
    return quote_fts_term(q)


def ensure_index(root: Path, db_path: Path) -> None:
    if not db_path.exists():
        rebuild(root, db_path)


def make_snippet(text: str, query: str, width: int = DEFAULT_SNIPPET_CHARS) -> str:
    folded = re.sub(r"\s+", " ", text).strip()
    idx = folded.lower().find(query.lower())
    if idx < 0:
        # Try first ascii token; otherwise start of document.
        tokens = re.findall(r"[A-Za-z0-9_\-]{2,}", query)
        for t in tokens:
            idx = folded.lower().find(t.lower())
            if idx >= 0:
                break
    if idx < 0:
        idx = 0
    start = max(0, idx - width // 3)
    end = min(len(folded), start + width)
    return ("..." if start else "") + folded[start:end] + ("..." if end < len(folded) else "")


def search(root: Path, db_path: Path, query: str, limit: int = 10, layer: Optional[str] = None) -> List[dict]:
    ensure_index(root, db_path)
    conn = connect(db_path)
    init_schema(conn)
    match_query = build_match_query(query)
    sql = """
        SELECT f.rowid, f.path, f.layer, f.title, f.text, bm25(docs_fts) AS rank
        FROM docs_fts AS f
        WHERE docs_fts MATCH ?
    """
    params: List[object] = [match_query]
    if layer:
        sql += " AND f.layer = ?"
        params.append(layer)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()

    # SQLite unicode61 tokenization is weak for CJK substring queries: a whole Chinese
    # sentence can become one token, so `MATCH "旁路记忆索引"` may miss
    # `长期助手使用旁路记忆索引`.  Keep FTS ranking first, then fill remaining
    # slots with a deterministic LIKE fallback over path/title/text.
    seen = {row["path"] for row in rows}
    if len(rows) < limit:
        like_sql = """
            SELECT rowid, path, layer, title, text, 0.0 AS rank
            FROM docs_fts
            WHERE (path LIKE ? OR title LIKE ? OR text LIKE ?)
        """
        like = f"%{query}%"
        like_params: List[object] = [like, like, like]
        if layer:
            like_sql += " AND layer = ?"
            like_params.append(layer)
        like_sql += " ORDER BY CASE WHEN title LIKE ? THEN 0 WHEN path LIKE ? THEN 1 ELSE 2 END, path LIMIT ?"
        like_params.extend([like, like, max(limit * 2, 10)])
        for row in conn.execute(like_sql, like_params).fetchall():
            if row["path"] in seen:
                continue
            rows.append(row)
            seen.add(row["path"])
            if len(rows) >= limit:
                break

    results = []
    for row in rows:
        results.append({
            "path": row["path"],
            "layer": row["layer"],
            "title": row["title"],
            "snippet": make_snippet(row["text"], query),
            "rank": row["rank"],
        })
    conn.close()
    return results


def stats_from_conn(conn: sqlite3.Connection) -> dict:
    counts = {row["layer"]: row["n"] for row in conn.execute("SELECT layer, COUNT(*) AS n FROM docs GROUP BY layer")}
    total = conn.execute("SELECT COUNT(*) AS n FROM docs").fetchone()["n"]
    return {"total": total, "by_layer": counts}


def stats(root: Path, db_path: Path) -> dict:
    ensure_index(root, db_path)
    conn = connect(db_path)
    init_schema(conn)
    out = stats_from_conn(conn)
    out["db"] = str(db_path)
    out["root"] = str(root.resolve())
    conn.close()
    return out


def check(root: Path, db_path: Path) -> dict:
    fts5 = has_fts5()
    collected = len(collect_docs(root)) if (root / "memory").exists() else 0
    db_exists = db_path.exists()
    return {"fts5": fts5, "memory_dir": str(root / "memory"), "collectable_docs": collected, "db": str(db_path), "db_exists": db_exists}


def emit(obj: object, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return
    if isinstance(obj, list):
        for i, item in enumerate(obj, 1):
            print(f"[{i}] {item['layer']} {item['path']} :: {item.get('title','')}")
            print(f"    {item.get('snippet','')}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            print(f"{k}: {v}")
    else:
        print(obj)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sidecar GA memory index/search helper")
    parser.add_argument("--root", type=Path, default=repo_root_from_here(), help="GA repo root (default: inferred)")
    parser.add_argument("--db", type=Path, default=None, help="SQLite index path (default: <root>/temp/memory_index.sqlite3)")
    parser.add_argument("--json", action="store_true", help="print JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json_flag(p: argparse.ArgumentParser) -> None:
        # argparse normally requires global options before the subcommand.
        # Add a suppressed duplicate so both `--json search x` and `search x --json` work.
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p = sub.add_parser("check", help="probe FTS5 and collectable docs")
    add_json_flag(p)

    p = sub.add_parser("rebuild", help="rebuild the index")
    p.add_argument("--no-l4", action="store_true", help="exclude memory/L4_raw_sessions")
    add_json_flag(p)

    p = sub.add_parser("stats", help="show index stats")
    add_json_flag(p)

    p = sub.add_parser("search", help="search memory")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--layer", choices=["L1", "L2", "L3", "L3.5", "L4", "memory"], default=None)
    add_json_flag(p)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    db_path = (args.db or default_db_path(root)).resolve()
    try:
        if args.cmd == "check":
            emit(check(root, db_path), args.json)
        elif args.cmd == "rebuild":
            emit(rebuild(root, db_path, include_l4=not args.no_l4), args.json)
        elif args.cmd == "stats":
            emit(stats(root, db_path), args.json)
        elif args.cmd == "search":
            emit(search(root, db_path, args.query, limit=args.limit, layer=args.layer), args.json)
        else:
            parser.error("unknown command")
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
