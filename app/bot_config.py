from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = DATA_DIR / "bot_config.json"


class BotConfig(BaseModel):
    enabled: bool = False
    dryRunOnly: bool = True
    allowBuy: bool = True
    allowSell: bool = True
    minConfidence: float = Field(default=0.62, ge=0, le=1)
    buyBelowResistancePct: float = Field(default=0.35, ge=0, le=20)
    sellAboveSupportPct: float = Field(default=0.35, ge=0, le=20)
    orderUsdt: float = Field(default=10, gt=0)
    sellQtyBtc: float = Field(default=0.0001, gt=0)
    dailyBudgetUsdt: float = Field(default=25, gt=0)
    checkIntervalMinutes: int = Field(default=15, ge=1, le=1440)


def read_bot_config(defaults: dict[str, Any] | None = None) -> BotConfig:
    payload: dict[str, Any] = dict(defaults or {})
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                payload.update(saved)
        except (OSError, json.JSONDecodeError):
            pass
    return BotConfig(**payload)


def write_bot_config(config: BotConfig) -> BotConfig:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return config
