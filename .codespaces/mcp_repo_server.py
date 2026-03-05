from __future__ import annotations
import asyncio
import os
import pathlib
from typing import List, Dict

from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware

REPO_DIR = pathlib.Path(os.environ.get("REPO_DIR", "/workspaces/repo")).resolve()
BRANCH = os.environ.get("BRANCH", "main")
SYNC_SEC = int(os.environ.get("SYNC_SECONDS", "120"))

mcp = FastMCP("RepoReadOnly", stateless_http=True, json_response=True)


def _safe(p: pathlib.Path) -> pathlib.Path:
    p = (REPO_DIR / p).resolve()
    if not str(p).startswith(str(REPO_DIR)):
        raise ValueError("Path outside repo")
    return p


@mcp.tool()
def list_files(glob_pattern: str = "**/*", limit: int = 500) -> List[str]:
    allowed_ext = {".md", ".txt", ".py", ".js", ".ts", ".json", ".css", ".html"}
    out: List[str] = []
    for path in REPO_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in allowed_ext:
            rel = str(path.relative_to(REPO_DIR))
            if pathlib.PurePosixPath(rel).match(glob_pattern):
                out.append(rel)
                if len(out) >= limit:
                    break
    return out


@mcp.tool()
def read_file(path: str, max_bytes: int = 200_000) -> str:
    p = _safe(pathlib.Path(path))
    data = p.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="replace")


@mcp.tool()
def search(query: str, glob_pattern: str = "**/*", max_hits: int = 50) -> List[Dict[str, object]]:
    hits: List[Dict[str, object]] = []
    for rel in list_files(glob_pattern=glob_pattern, limit=10_000):
        p = REPO_DIR / rel
        try:
            for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
                if query in line:
                    hits.append({"file": rel, "line": i, "text": line.strip()})
                    if len(hits) >= max_hits:
                        return hits
        except Exception:
            pass
    return hits


async def _sync_loop() -> None:
    while True:
        os.system(f"git -C '{REPO_DIR}' fetch --all --prune")
        os.system(f"git -C '{REPO_DIR}' reset --hard origin/{BRANCH}")
        await asyncio.sleep(SYNC_SEC)


app = mcp.streamable_http_app()
app = CORSMiddleware(
    app,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
    expose_headers=["Mcp-Session-Id"],
)


if __name__ == "__main__":
    import threading
    import uvicorn

    threading.Thread(target=lambda: asyncio.run(_sync_loop()), daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8000)
