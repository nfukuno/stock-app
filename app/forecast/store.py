"""予想の保存先。LocalStore（作業ツリー）と GitHubStore（Contents API）。"""
from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from pathlib import Path

import requests

from . import config


def rel_path(target_date: str, symbol: str) -> str:
    y, m, _ = target_date.split("-")
    return f"{y}/{m}/{target_date}_{symbol}.json"


class ForecastStore(ABC):
    @abstractmethod
    def get(self, target_date: str, symbol: str) -> dict | None: ...

    @abstractmethod
    def put(self, pred: dict, message: str | None = None) -> None: ...

    @abstractmethod
    def list_all(self) -> list[dict]: ...

    @abstractmethod
    def read_text(self, rel: str) -> str | None: ...

    @abstractmethod
    def write_text(self, rel: str, text: str, message: str | None = None) -> None: ...


def dumps(pred: dict) -> str:
    return json.dumps(pred, ensure_ascii=False, indent=2) + "\n"


class LocalStore(ForecastStore):
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else config.data_dir()

    def get(self, target_date, symbol):
        p = self.root / rel_path(target_date, symbol)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put(self, pred, message=None):
        self.write_text(rel_path(pred["target_date"], pred["symbol"]), dumps(pred))

    def list_all(self):
        if not self.root.exists():
            return []
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.root.glob("*/*/*.json"))]

    def read_text(self, rel):
        p = self.root / rel
        return p.read_text(encoding="utf-8") if p.exists() else None

    def write_text(self, rel, text, message=None):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


class GitHubStore(ForecastStore):
    API = "https://api.github.com"

    def __init__(self, repo=None, branch=None, token=None, prefix="forecasts"):
        self.repo = repo or config.github_repo()
        self.branch = branch or config.github_branch()
        self.token = token if token is not None else config.github_token()
        self.prefix = prefix

    def _headers(self):
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _url(self, rel):
        return f"{self.API}/repos/{self.repo}/contents/{self.prefix}/{rel}"

    def _get_file(self, rel):
        r = requests.get(self._url(rel), headers=self._headers(), params={"ref": self.branch}, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def read_text(self, rel):
        info = self._get_file(rel)
        if info is None:
            return None
        if info.get("content"):
            return base64.b64decode(info["content"]).decode("utf-8")
        # 1MB 超は raw で取得
        r = requests.get(self._url(rel), headers={**self._headers(), "Accept": "application/vnd.github.raw+json"},
                         params={"ref": self.branch}, timeout=30)
        r.raise_for_status()
        return r.text

    def write_text(self, rel, text, message=None):
        info = self._get_file(rel)
        body = {
            "message": message or f"Update {self.prefix}/{rel}",
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": self.branch,
        }
        if info is not None:
            body["sha"] = info["sha"]
        r = requests.put(self._url(rel), headers=self._headers(), json=body, timeout=30)
        r.raise_for_status()

    def get(self, target_date, symbol):
        text = self.read_text(rel_path(target_date, symbol))
        return json.loads(text) if text is not None else None

    def put(self, pred, message=None):
        msg = message or f"forecast: {pred['id']}"
        self.write_text(rel_path(pred["target_date"], pred["symbol"]), dumps(pred), msg)

    def list_all(self):
        r = requests.get(f"{self.API}/repos/{self.repo}/git/trees/{self.branch}", headers=self._headers(),
                         params={"recursive": "1"}, timeout=30)
        r.raise_for_status()
        out = []
        for node in r.json().get("tree", []):
            path = node["path"]
            if path.startswith(self.prefix + "/") and path.endswith(".json") and path.count("/") == 3:
                text = self.read_text(path[len(self.prefix) + 1:])
                if text:
                    out.append(json.loads(text))
        return out


def get_store() -> ForecastStore:
    return GitHubStore() if config.storage_mode() == "github" else LocalStore()
