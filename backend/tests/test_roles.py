import json
from app.pipeline.roles import (
    analyze_jd, extract_profile, screen_resume, evaluate_resume, summarize_ranking,
)
from app.schemas import JDParsed, ResumeProfile, ScreeningResult, EvaluationResult, FinalReport


class RoleLLMFake:
    """按 role 返回预制 JSON。"""
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def chat_json(self, role, system_prompt, user_prompt, schema, **kw):
        self.calls.append({"role": role, "user_prompt": user_prompt})
        return schema.model_validate(self.responses[role])


JD = JDParsed(responsibilities=["负责服务端开发"],
              hard_requirements=[{"description": "本科及以上", "weight": 0.5}],
              bonus_items=["有大型项目经验"])
PROFILE = {"name": "张三", "education": [], "work_experience": [],
           "skills": ["Go"], "projects": [], "certificates": []}


async def test_analyze_jd():
    llm = RoleLLMFake({"jd_analyst": JD.model_dump()})
    out = await analyze_jd(llm, "资深后端工程师，要求本科...")
    assert out.hard_requirements[0].weight == 0.5


async def test_extract_profile_passes_resume_text():
    llm = RoleLLMFake({"extractor": PROFILE})
    out = await extract_profile(llm, "张三的简历全文", resume_id=1)
    assert out.name == "张三"
    assert "张三的简历全文" in llm.calls[0]["user_prompt"]


async def test_screen_resume_receives_both_inputs():
    llm = RoleLLMFake({"screener": {"passed": False, "checks": [], "reject_reason": "学历不符"}})
    out = await screen_resume(llm, JD, ResumeProfile.model_validate(PROFILE), resume_id=1)
    assert out.passed is False
    prompt = llm.calls[0]["user_prompt"]
    assert "本科及以上" in prompt and "张三" in prompt  # JD 与档案都要在提示词里


async def test_evaluate_resume():
    resp = {"skill_match": 80, "experience_match": 70, "stability": 90, "potential": 60,
            "highlights": ["x"], "risks": ["y"], "gaps": ["z"], "interview_questions": ["q"]}
    llm = RoleLLMFake({"interviewer": resp})
    out = await evaluate_resume(llm, JD, ResumeProfile.model_validate(PROFILE), resume_id=1)
    assert out.skill_match == 80


async def test_summarize_ranking():
    resp = {"rankings": [{"resume_id": 1, "grade": "A", "rank": 1, "comment": "强推"}],
            "summary": "总体优秀"}
    llm = RoleLLMFake({"hr_manager": resp})
    out = await summarize_ranking(llm, JD, [{"resume_id": 1, "profile": PROFILE}])
    assert out.rankings[0].rank == 1
    assert "1" in llm.calls[0]["user_prompt"]  # resume_id 出现在提示词中
