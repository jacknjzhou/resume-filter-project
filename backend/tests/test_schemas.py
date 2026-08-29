import pytest
from pydantic import ValidationError
from app.schemas import (
    JDParsed, ResumeProfile, ScreeningResult, EvaluationResult, FinalReport,
)


def test_jd_parsed_minimal():
    jd = JDParsed(responsibilities=[], hard_requirements=[], bonus_items=[])
    assert jd.responsibilities == []


def test_evaluation_score_bounds():
    with pytest.raises(ValidationError):
        EvaluationResult(skill_match=101, experience_match=0, stability=0,
                         potential=0, highlights=[], risks=[], gaps=[],
                         interview_questions=[])
    ok = EvaluationResult(skill_match=80, experience_match=70, stability=90,
                          potential=60, highlights=["a"], risks=["b"],
                          gaps=["c"], interview_questions=["q1"])
    assert ok.skill_match == 80


def test_screening_reject_reason_optional():
    s = ScreeningResult(passed=False, checks=[], reject_reason=None)
    assert s.passed is False


def test_final_report_shape():
    r = FinalReport(rankings=[{"resume_id": 1, "grade": "A", "rank": 1, "comment": "强推"}],
                    summary="共 1 人")
    assert r.rankings[0].grade == "A"


def test_resume_profile_shape():
    p = ResumeProfile.model_validate({
        "name": "李四",
        "education": [{"school": "X大", "degree": "本科", "major": "CS", "period": "2015-2019"}],
        "work_experience": [{"company": "A公司", "title": "后端", "period": "2019-至今", "summary": "Go 微服务"}],
        "skills": ["Go"], "projects": ["p"], "certificates": [],
    })
    assert p.work_experience[0].company == "A公司"
