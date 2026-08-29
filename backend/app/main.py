from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import Base, engine
from app.routers import tasks, resumes


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="简历审阅系统", lifespan=lifespan)

app.include_router(tasks.router)
app.include_router(resumes.router)
