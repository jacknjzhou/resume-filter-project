from sqlalchemy.orm import Session

from app.models import AppSetting

# 页面可编辑的运行参数及类型（部署级配置 database_url/uploads_dir 不在此列）
EDITABLE_KEYS: dict[str, type] = {
    "llm_base_url": str,
    "llm_api_key": str,
    "llm_model": str,
    "llm_vlm_model": str,
    "llm_timeout": float,
    "ocr_base_url": str,
    "ocr_confidence_threshold": float,
    "step_timeout": int,
    "max_concurrency": int,
}


def load_overrides(db: Session) -> dict[str, str]:
    rows = db.query(AppSetting).filter(AppSetting.key.in_(EDITABLE_KEYS)).all()
    return {r.key: r.value for r in rows}


def save_overrides(db: Session, values: dict[str, str]):
    for k, v in values.items():
        if k not in EDITABLE_KEYS:
            raise ValueError(f"不可配置项：{k}")
        row = db.get(AppSetting, k)
        if row is None:
            db.add(AppSetting(key=k, value=str(v)))
        else:
            row.value = str(v)
    db.commit()


def apply_to_settings(settings_obj, overrides: dict[str, str]):
    """把 DB 覆盖值原地赋到 Settings 单例上（lru_cache 单例被各模块持有，
    原地赋值即对所有使用方生效）。未知键忽略。"""
    for k, v in overrides.items():
        if k in EDITABLE_KEYS:
            setattr(settings_obj, k, EDITABLE_KEYS[k](v))
