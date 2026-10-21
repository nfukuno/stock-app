"""口座の保存。日足予想と同じ LocalStore / GitHubStore を trades/ 以下で使う。

trades/current.json           … {"account_id": ...} 現在使っている口座
trades/accounts/{id}.json     … 口座（建玉・約定履歴）。リセットしても過去の口座は残す
"""
from __future__ import annotations

import json

from app.forecast.store import ForecastStore, GitHubStore, LocalStore, dumps
from . import config

CURRENT = "current.json"


def account_rel(account_id: str) -> str:
    return f"accounts/{account_id}.json"


def get_store() -> ForecastStore:
    if config.storage_mode() == "github":
        return GitHubStore(prefix=config.GITHUB_PREFIX)
    return LocalStore(root=config.data_dir())


def load_current(store: ForecastStore) -> dict | None:
    cur = store.read_text(CURRENT)
    if not cur:
        return None
    text = store.read_text(account_rel(json.loads(cur)["account_id"]))
    return json.loads(text) if text else None


def save(store: ForecastStore, acct: dict, message: str, make_current: bool = False) -> None:
    store.write_text(account_rel(acct["id"]), dumps(acct), f"trade: {message}")
    if make_current:
        store.write_text(CURRENT, dumps({"account_id": acct["id"]}), f"trade: switch account {acct['id']}")
