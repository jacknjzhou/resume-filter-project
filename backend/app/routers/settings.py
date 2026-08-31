from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.settings_store import (
    EDITABLE_KEYS, apply_to_settings, load_overrides, save_overrides)

router = APIRouter(prefix="/api")


class SettingsUpdate(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_vlm_model: str | None = None
    llm_timeout: float | None = None
    ocr_base_url: str | None = None
    ocr_confidence_threshold: float | None = None
    step_timeout: int | None = None
    max_concurrency: int | None = None


@router.get("/settings")
def read_settings(db: Session = Depends(get_db)):
    s = get_settings()
    overridden = load_overrides(db)
    return {"editable": {
        k: {"value": getattr(s, k), "overridden": k in overridden,
            "type": t.__name__}
        for k, t in EDITABLE_KEYS.items()
    }}


@router.put("/settings")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    values = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not values:
        raise HTTPException(422, "没有可更新的配置项")
    # 未知键（不在 SettingsUpdate 定义中）会被 pydantic 静默忽略，
    # 但为防模型字段与 EDITABLE_KEYS 漂移，这里再显式校验一次
    bad = set(values) - set(EDITABLE_KEYS)
    if bad:
        raise HTTPException(422, f"不可配置项：{', '.join(sorted(bad))}")
    try:
        SettingsUpdate.model_validate(values)  # 类型兜底校验
        if "llm_timeout" in values and values["llm_timeout"] <= 0:
            raise ValueError("llm_timeout 必须为正数")
        if "step_timeout" in values and values["step_timeout"] <= 0:
            raise ValueError("step_timeout 必须为正数")
        if "max_concurrency" in values and not (1 <= values["max_concurrency"] <= 10):
            raise ValueError("max_concurrency 取值 1-10")
        if "ocr_confidence_threshold" in values and not (
                0 < values["ocr_confidence_threshold"] <= 1):
            raise ValueError("ocr_confidence_threshold 取值 (0, 1]")
    except (ValidationError, ValueError) as e:
        raise HTTPException(422, str(e))

    str_values = {k: str(v) for k, v in values.items()}
    save_overrides(db, str_values)
    apply_to_settings(get_settings(), str_values)
    return {"ok": True}
