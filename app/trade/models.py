"""注文の入力モデル（検証）。口座・建玉・約定は dict(JSON) のまま扱う。"""
from __future__ import annotations

from datetime import date, datetime
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
    horizon: Literal["day", "swing"] = "day"
    margin_type: Literal["day", "system", "general", "cash"]
    side: Literal["long", "short"]
    qty: int = Field(gt=0)
    price: float = Field(gt=0)
    executed_at: datetime | None = None        # 省略時は現在時刻
    # 3行メモ（必須）: 型と根拠 / 無効化（損切り）/ 目標
    setup: str
    plan_basis: str = Field(min_length=1, max_length=c.PLAN_TEXT_MAX)
    stop: float = Field(gt=0)
    plan_exit_rule: str = Field(default="", max_length=c.PLAN_TEXT_MAX)
    target: float = Field(gt=0)
    plan_target_basis: str = Field(default="", max_length=c.PLAN_TEXT_MAX)
    tags: list[str] = Field(default_factory=list)
    emotion: str = ""
    memo: str = Field(default="", max_length=c.MEMO_MAX)
    # スイング用（デイトレでは空のまま）
    decision_date: date | None = None          # 判断した足の日付（日足確定日）。省略時は建日
    entry_method: str | None = None            # config.ENTRY_METHODS のキー。スイングでは必須
    judge_stop: float | None = Field(default=None, gt=0)       # 判断ストップ（終値基準）
    next_wall_price: float | None = Field(default=None, gt=0)  # 次の壁。スイングでは必須
    next_wall_kind: str = Field(default="", max_length=40)
    earnings_date: date | None = None          # 次回決算日（不明なら空）

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

    @field_validator("setup")
    @classmethod
    def _setup(cls, v):
        if v not in c.SETUPS:
            raise ValueError("型を選んでください")
        return v

    @field_validator("plan_basis", "plan_exit_rule", "plan_target_basis")
    @classmethod
    def _strip(cls, v, info):
        v = v.strip()
        if info.field_name == "plan_basis" and not v:
            raise ValueError("3行メモの根拠を入力してください")
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

    @field_validator("entry_method")
    @classmethod
    def _entry_method(cls, v):
        if v and v not in c.ENTRY_METHODS:
            raise ValueError(f"エントリー方法は {list(c.ENTRY_METHODS)} のいずれか")
        return v or None

    @model_validator(mode="after")
    def _levels(self):
        sign = 1 if self.side == "long" else -1
        if not c.MARGIN_TYPES[self.margin_type]["short"] and self.side == "short":
            raise ValueError("現物では売り（空売り）はできません。信用取引を選んでください")
        if self.horizon == "swing":
            if self.margin_type == "day":
                raise ValueError("スイング（持ち越し）では、いちにち信用は使えません。現物・制度信用・一般信用から選んでください")
            if not self.entry_method:
                raise ValueError("スイングではエントリー方法を選んでください")
            if self.next_wall_price is None:
                raise ValueError("スイングでは次の壁の価格を入れてください")
            if (self.next_wall_price - self.price) * sign <= 0:
                raise ValueError("次の壁は、買いなら建値より上、売りなら建値より下の価格にしてください")
            if self.judge_stop is not None and not ((self.judge_stop - self.stop) * sign > 0 and (self.price - self.judge_stop) * sign > 0):
                raise ValueError("判断ストップは、保険ストップと建値の間に置いてください")
        else:                                       # デイトレではスイング用の項目を持たない
            for k in ("decision_date", "entry_method", "judge_stop", "next_wall_price", "earnings_date"):
                setattr(self, k, None)
            self.next_wall_kind = ""
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
    exit_type: str = ""                         # config.EXIT_TYPES のキー（空 = 未分類）

    @field_validator("exit_type")
    @classmethod
    def _exit_type(cls, v):
        if v and v not in c.EXIT_TYPES:
            raise ValueError(f"決済理由は {list(c.EXIT_TYPES)} のいずれか")
        return v

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
    exit_type: str = ""                         # config.EXIT_TYPES のキー（空 = 未分類）

    @field_validator("exit_type")
    @classmethod
    def _exit_type(cls, v):
        if v and v not in c.EXIT_TYPES:
            raise ValueError(f"決済理由は {list(c.EXIT_TYPES)} のいずれか")
        return v

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


class EditIn(BaseModel):
    """後からの修正・追記。送った項目だけ変更する（null は「変更しない」）。"""
    open_price: float | None = Field(default=None, gt=0)
    close_price: float | None = Field(default=None, gt=0)
    stop: float | None = Field(default=None, gt=0)
    target: float | None = Field(default=None, gt=0)
    tags: list[str] | None = None
    emotion: str | None = None
    memo: str | None = Field(default=None, max_length=c.MEMO_MAX)
    exit_memo: str | None = Field(default=None, max_length=c.MEMO_MAX)
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    exit_type: str | None = None
    setup: str | None = None
    horizon: Literal["day", "swing"] | None = None
    decision_date: date | None = None
    entry_method: str | None = None
    judge_stop: float | None = Field(default=None, gt=0)
    next_wall_price: float | None = Field(default=None, gt=0)
    next_wall_kind: str | None = Field(default=None, max_length=40)
    earnings_date: date | None = None
    reverse_fee: int | None = Field(default=None, ge=0)       # 逆日歩（円）。制度信用の売りで発生
    hold_high: float | None = Field(default=None, gt=0)       # 保有中の最高値（MFE/MAE 用）
    hold_low: float | None = Field(default=None, gt=0)        # 保有中の最安値
    plan_basis: str | None = Field(default=None, max_length=c.PLAN_TEXT_MAX)
    plan_exit_rule: str | None = Field(default=None, max_length=c.PLAN_TEXT_MAX)
    plan_target_basis: str | None = Field(default=None, max_length=c.PLAN_TEXT_MAX)

    @field_validator("setup")
    @classmethod
    def _setup(cls, v):
        if v is not None and v not in c.SETUPS:
            raise ValueError("型が不正です")
        return v

    @field_validator("entry_method")
    @classmethod
    def _entry_method(cls, v):
        if v and v not in c.ENTRY_METHODS:
            raise ValueError("エントリー方法が不正です")
        return v

    @field_validator("plan_basis")
    @classmethod
    def _basis(cls, v):
        if v is not None and not v.strip():
            raise ValueError("3行メモの根拠は空にできません")
        return v if v is None else v.strip()

    @field_validator("exit_type")
    @classmethod
    def _exit_type(cls, v):
        if v and v not in c.EXIT_TYPES:
            raise ValueError(f"決済理由は {list(c.EXIT_TYPES)} のいずれか")
        return v

    @field_validator("opened_at", "closed_at", mode="before")
    @classmethod
    def _time(cls, v):
        return _parse_time(v)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v):
        return None if v is None else OpenIn._tags(v)

    @field_validator("emotion")
    @classmethod
    def _emotion(cls, v):
        return None if v is None else OpenIn._emotion(v)

    def changes(self) -> dict:
        d = self.model_dump(exclude_unset=True)
        # null は「変更しない」。ただしスイングの任意項目は "" で消せる（下で None に変換）
        clearable = ("judge_stop", "earnings_date", "decision_date", "next_wall_kind", "hold_high", "hold_low")
        for k in list(d):
            if d[k] is None and k not in clearable:
                del d[k]
        return d


class ResetIn(BaseModel):
    initial_cash: int = Field(default=c.INITIAL_CASH, ge=c.MIN_MARGIN, le=1_000_000_000)
