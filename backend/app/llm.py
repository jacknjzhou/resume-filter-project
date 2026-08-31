import asyncio
import json
import time
from pydantic import BaseModel, ValidationError
from openai import AsyncOpenAI
from sqlalchemy.orm import Session
from app.models import LLMLog

MAX_ATTEMPTS = 3  # 首次 + 2 次重试
RETRY_BACKOFF_SECONDS = 0.5  # 网络/服务异常重试前的退避


class LLMError(Exception):
    def __init__(self, message: str, attempts: int):
        super().__init__(message)
        self.attempts = attempts


class LLMClient:
    def __init__(self, settings, db: Session):
        self.settings = settings
        self.db = db
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url if settings else None,
            api_key=settings.llm_api_key if settings else "EMPTY",
            timeout=settings.llm_timeout if settings else 120,
        )

    async def chat_json(self, role, system_prompt, user_prompt, schema: type[BaseModel],
                        task_id=None, model=None, resume_id=None):
        last_err = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            prompt = user_prompt
            if attempt > 1 and last_err is not None:
                prompt = (f"{user_prompt}\n\n上次输出未通过校验，错误信息：{last_err}。"
                          f"请严格按 JSON Schema 重新输出，不要输出任何多余文字。")
            start = time.monotonic()
            try:
                resp = await self._client.chat.completions.create(
                    model=model or (self.settings.llm_model if self.settings else "test-model"),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content
                usage = resp.usage
            except Exception as e:  # 网络/服务错误也计一次尝试
                last_err = str(e)
                self._log(task_id, role, 0, 0, start, resume_id)
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                continue
            try:
                result = schema.model_validate_json(content)
            except ValidationError as e:
                last_err = str(e)
                self._log(task_id, role, usage.prompt_tokens, usage.completion_tokens,
                          start, resume_id)
                continue
            self._log(task_id, role, usage.prompt_tokens, usage.completion_tokens,
                      start, resume_id)
            return result
        raise LLMError(f"角色 {role} 在 {MAX_ATTEMPTS} 次尝试后仍未产出合法 JSON：{last_err}",
                       attempts=MAX_ATTEMPTS)

    def _log(self, task_id, role, ptok, ctok, start, resume_id=None):
        self.db.add(LLMLog(task_id=task_id, role=role, resume_id=resume_id,
                           prompt_tokens=ptok or 0, completion_tokens=ctok or 0,
                           duration_ms=int((time.monotonic() - start) * 1000)))
        self.db.commit()

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False
