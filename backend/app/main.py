from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import Base, engine
from app.routers import tasks, resumes, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    _load_setting_overrides()
    yield


def _load_setting_overrides():
    from app.config import get_settings
    from app.db import SessionLocal
    from app.settings_store import apply_to_settings, load_overrides
    db = SessionLocal()
    try:
        apply_to_settings(get_settings(), load_overrides(db))
    except Exception:
        pass  # 配置表异常不阻断启动，退回 env 默认值
    finally:
        db.close()


app = FastAPI(title="简历审阅系统", lifespan=lifespan)

app.include_router(tasks.router)
app.include_router(resumes.router)
app.include_router(settings.router)
