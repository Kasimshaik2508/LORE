"""Importers: a local folder of records/docs, or a live GitHub repository."""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests


def load_folder(path: str | Path) -> tuple[list[dict], dict]:
    """Read records.json, docs/*.md and services.json from a folder."""
    root = Path(path)
    records: list[dict] = []
    rec_file = root / "records.json"
    if rec_file.exists():
        records += json.loads(rec_file.read_text())
    for md in sorted(root.rglob("*.md")):
        records.append({
            "id": f"DOC-{md.stem.upper()}",
            "type": "doc",
            "title": md.stem.replace("_", " ").title(),
            "author": "",
            "reviewers": [],
            "date": "",
            "url": str(md.relative_to(root)),
            "files": [],
            "body": md.read_text(),
            "comments": [],
        })
    services = {}
    svc_file = root / "services.json"
    if svc_file.exists():
        services = json.loads(svc_file.read_text()).get("services", {})
    return records, services


class GitHub:
    """Minimal GitHub REST importer. Works unauthenticated on public repos (60 req/h);
    set GITHUB_TOKEN for more."""

    def __init__(self, repo: str):
        self.repo = repo
        self.s = requests.Session()
        self.s.headers["Accept"] = "application/vnd.github+json"
        if os.getenv("GITHUB_TOKEN"):
            self.s.headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"

    def _get(self, path: str, **params):
        r = self.s.get(f"https://api.github.com/repos/{self.repo}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def merged_prs(self, limit: int = 20, since: str = "") -> list[dict]:
        out = []
        for pr in self._get("/pulls", state="closed", sort="updated", direction="desc", per_page=min(limit, 100)):
            if not pr.get("merged_at") or (since and pr["merged_at"] <= since):
                continue
            n = pr["number"]
            comments = [
                {"author": c["user"]["login"], "body": c.get("body") or ""}
                for c in self._get(f"/issues/{n}/comments", per_page=50)
            ]
            comments += [
                {"author": c["user"]["login"], "body": c.get("body") or ""}
                for c in self._get(f"/pulls/{n}/reviews", per_page=50) if c.get("body")
            ]
            files = [f["filename"] for f in self._get(f"/pulls/{n}/files", per_page=100)]
            out.append({
                "id": f"PR-{n}",
                "type": "merge_request",
                "title": pr["title"],
                "author": pr["user"]["login"],
                "reviewers": sorted({c["author"] for c in comments} - {pr["user"]["login"]}),
                "date": pr["merged_at"][:10],
                "merged_at": pr["merged_at"],
                "url": pr["html_url"],
                "files": files,
                "body": pr.get("body") or "",
                "comments": comments,
            })
        return out

    def readme(self) -> dict | None:
        try:
            data = self.s.get(f"https://api.github.com/repos/{self.repo}/readme",
                              headers={"Accept": "application/vnd.github.raw"}, timeout=30)
            data.raise_for_status()
        except requests.HTTPError:
            return None
        return {"id": "DOC-README", "type": "doc", "title": "README", "author": "", "reviewers": [],
                "date": "", "url": f"https://github.com/{self.repo}#readme", "files": [],
                "body": data.text[:20000], "comments": []}
