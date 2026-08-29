from pydantic import BaseModel, Field


class JDRequirement(BaseModel):
    description: str
    weight: float


class JDParsed(BaseModel):
    responsibilities: list[str]
    hard_requirements: list[JDRequirement]
    bonus_items: list[str]


class Education(BaseModel):
    school: str
    degree: str
    major: str
    period: str


class WorkExperience(BaseModel):
    company: str
    title: str
    period: str
    summary: str


class ResumeProfile(BaseModel):
    name: str
    education: list[Education]
    work_experience: list[WorkExperience]
    skills: list[str]
    projects: list[str]
    certificates: list[str]


class ScreeningCheck(BaseModel):
    requirement: str
    met: bool
    evidence: str


class ScreeningResult(BaseModel):
    passed: bool
    checks: list[ScreeningCheck]
    reject_reason: str | None = None


class EvaluationResult(BaseModel):
    skill_match: int = Field(ge=0, le=100)
    experience_match: int = Field(ge=0, le=100)
    stability: int = Field(ge=0, le=100)
    potential: int = Field(ge=0, le=100)
    highlights: list[str]
    risks: list[str]
    gaps: list[str]
    interview_questions: list[str]


class FinalRankingItem(BaseModel):
    resume_id: int
    grade: str
    rank: int
    comment: str


class FinalReport(BaseModel):
    rankings: list[FinalRankingItem]
    summary: str


class TextCorrection(BaseModel):
    corrected: str
