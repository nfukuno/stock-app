"""注文の入力モデル（検証）。口座・建玉・約定は dict(JSON) のまま扱う。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import config as c


def _parse_time(v):
    if v in (None, ""):
        return None
    dt = datetime.fromisoformat(v) if isinstance(v, str) else v
    if dt.tzinfo is None:                      # 画面の datetime-local は JST とみなす
        from app.forecast.market import JST
        dt = dt.replace(tzinfo=JST)
    return dt


class OpenIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=12)
    name: str = Field(default="", max_length=40)
    margin_type: Literal["day", "system"]
    side: Literal["long", "short"]
    qty: int = Field(gt=0)
    price: float = Field(gt=0)
    executed_at: datetime | None = None        # 省略時は現在時刻
    stop: float | None = Field(default=None, gt=0)
    target: float | None = Field(default=None, gt=0)
    tags: list[str] = Field(default_factory=list)
    emotion: str = ""
    memo: str = Field(default="", max_length=c.MEMO_MAX)

    @field_validator("executed_at", mode="before")
    @classmethod
    def _time(cls, v):
        return _parse_time(v)

    @field_validator("qty")
    @classmethod
    def _lot(cls, v):
        if v % c.LOT:
            raise ValueError(f"株数は {c.LOT} 株単位です")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v):
        bad = [t for t in v if t not in c.TAGS]
        if bad:
            raise ValueError(f"不明なタグ: {bad}")
        return list(dict.fromkeys(v))

    @field_validator("emotion")
    @classmethod
    def _emotion(cls, v):
        if v and v not in c.EMOTIONS:
            raise ValueError(f"感情は {c.EMOTIONS} のいずれか")
        return v

    @model_validator(mode="after")
    def _levels(self):
        sign = 1 if self.side == "long" else -1
        if self.stop is not None and (self.stop - self.price) * sign >= 0:
            raise ValueError("損切りラインは買いなら建値より下、売りなら建値より上に置いてください")
        if self.target is not None and (self.target - self.price) * sign <= 0:
            raise ValueError("利確目標は買いなら建値より上、売りなら建値より下に置いてください")
        return self


class CloseIn(BaseModel):
    position_id: str
    qty: int = Field(gt=0)
    price: float = Field(gt=0)
    executed_at: datetime | None = None
    memo: str = Field(default="", max_length=c.MEMO_MAX)

    @field_validator("executed_at", mode="before")
    @classmethod
    def _time(cls, v):
        return _parse_time(v)

    @field_validator("qty")
    @classmethod
    def _lot(cls, v):
        if v % c.LOT:
            raise ValueError(f"株数は {c.LOT} 株単位です")
        return v


class CloseGroupIn(BaseModel):
    key: str                                   # engine.group_key（銘柄|売買|区分）
    qty: int = Field(gt=0)
    price: float = Field(gt=0)
    executed_at: datetime | None = None
    memo: str = Field(default="", max_length=c.MEMO_MAX)

    @field_validator("executed_at", mode="before")
    @classmethod
    def _time(cls, v):
        return _parse_time(v)

    @field_validator("qty")
    @classmethod
    def _lot(cls, v):
        if v % c.LOT:
            raise ValueError(f"株数は {c.LOT} 株単位です")
        return v


class ResetIn(BaseModel):
    initial_cash: int = Field(default=c.INITIAL_CASH, ge=c.MIN_MARGIN, le=1_000_000_000)
