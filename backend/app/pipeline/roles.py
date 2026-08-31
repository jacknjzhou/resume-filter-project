import json
from functools import lru_cache
from pathlib import Path
from app.schemas import (
    JDParsed, ResumeProfile, ScreeningResult, EvaluationResult, FinalReport,
)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@lru_cache(maxsize=16)
def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


async def analyze_jd(llm, jd_text: str, task_id=None) -> JDParsed:
    return await llm.chat_json("jd_analyst", _prompt("jd_analyst"),
                               f"JD 原文：\n{jd_text}", JDParsed, task_id=task_id)


async def extract_profile(llm, resume_text: str, resume_id: int, task_id=None) -> ResumeProfile:
    return await llm.chat_json("extractor", _prompt("extractor"),
                               f"简历文本：\n{resume_text}", ResumeProfile,
                               task_id=task_id, resume_id=resume_id)


async def screen_resume(llm, jd_parsed: JDParsed, profile: ResumeProfile,
                        resume_id: int, task_id=None) -> ScreeningResult:
    user = (f"结构化 JD：\n{_dump(jd_parsed.model_dump())}\n\n"
            f"候选人档案（resume_id={resume_id}）：\n{_dump(profile.model_dump())}")
    return await llm.chat_json("screener", _prompt("screener"), user,
                               ScreeningResult, task_id=task_id, resume_id=resume_id)


async def evaluate_resume(llm, jd_parsed: JDParsed, profile: ResumeProfile,
                          resume_id: int, task_id=None) -> EvaluationResult:
    user = (f"结构化 JD：\n{_dump(jd_parsed.model_dump())}\n\n"
            f"候选人档案（resume_id={resume_id}）：\n{_dump(profile.model_dump())}")
    return await llm.chat_json("interviewer", _prompt("interviewer"), user,
                               EvaluationResult, task_id=task_id, resume_id=resume_id)


async def summarize_ranking(llm, jd_parsed: JDParsed, items: list[dict],
                            task_id=None) -> FinalReport:
    user = (f"结构化 JD：\n{_dump(jd_parsed.model_dump())}\n\n"
            f"通过初筛的候选人评估结果：\n{_dump(items)}")
    return await llm.chat_json("hr_manager", _prompt("hr_manager"), user,
                               FinalReport, task_id=task_id)
