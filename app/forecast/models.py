"""予想の入力モデル（検証）。保存形式は dict(JSON) のまま扱う。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from . import config as c


class Pred(BaseModel):
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)

    @model_validator(mode="after")
    def _check(self):
        if self.high < max(self.open, self.close):
            raise ValueError("high は open/close 以上である必要があります")
        if self.low > min(self.open, self.close):
            raise ValueError("low は open/close 以下である必要があります")
        return self

    def rounded(self) -> dict:
        return {k: round(getattr(self, k), 1) for k in ("open", "high", "low", "close")}


class ForecastIn(BaseModel):
    symbol: str
    target_date: str
    pred: Pred
    scenario: str
    confidence: int = Field(ge=1, le=5)
    memo: str = Field(default="", max_length=c.MEMO_MAX)
    name: str = Field(default="", max_length=40)

    @field_validator("scenario")
    @classmethod
    def _scenario(cls, v: str) -> str:
        if v not in c.SCENARIO_KEYS:
            raise ValueError(f"scenario は {c.SCENARIO_KEYS} のいずれか")
        return v


def prediction_id(target_date: str, symbol: str) -> str:
    return f"{target_date}_{symbol}"
