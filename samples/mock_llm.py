"""极简 OpenAI 兼容 mock LLM：按提示词中的角色关键词返回预制 JSON。
运行：uvicorn --app-dir samples mock_llm:app --port 8000"""
import json
import re
from fastapi import FastAPI, Request

app = FastAPI()

JD = {"responsibilities": ["服务端开发"], "hard_requirements": [{"description": "本科", "weight": 0.5}],
      "bonus_items": []}
PROFILE_OK = {"name": "张三/李四", "education": [{"school": "985", "degree": "本科", "major": "CS", "period": ""}],
              "work_experience": [{"company": "大厂", "title": "后端", "period": "5年",
                                   "summary": "Go/Python，日活百万微服务"}],
              "skills": ["Go", "Python", "微服务"], "projects": ["高并发系统"],
              "certificates": []}
PROFILE_WEAK = {"name": "王五",
                "education": [{"school": "X", "degree": "大专", "major": "", "period": ""}],
                "work_experience": [{"company": "A", "title": "前端", "period": "1年", "summary": ""}],
                "skills": [], "projects": [], "certificates": []}
SCREEN_OK = {"passed": True, "checks": [], "reject_reason": None}
SCREEN_REJECT = {"passed": False, "checks": [], "reject_reason": "经验不足"}
EVAL = {"skill_match": 75, "experience_match": 70, "stability": 85, "potential": 65,
        "highlights": ["经验扎实"], "risks": [], "gaps": [],
        "interview_questions": ["介绍最有挑战的项目？"]}
REPORT = {"rankings": [], "summary": "整体符合要求"}  # rankings 由调用方填 resume_id


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "mock"}]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text = json.dumps(body["messages"], ensure_ascii=False)
    m = re.search(r"resume_id=(\d+)", text)
    rid = int(m.group(1)) if m else 0

    if "jd_analyst" in text or "JD 解析官" in text:
        content = JD
    elif "简历文本" in text and "skills" in text:
        content = PROFILE_WEAK if "王五" in text else PROFILE_OK
    elif "初筛专员" in text:
        content = SCREEN_REJECT if "王五" in text or "1 年" in text else SCREEN_OK
    elif "资深面试官" in text:
        content = EVAL
    else:  # HR 主管
        report = dict(REPORT)
        ids = [int(x) for x in re.findall(r'resume_id\\?["\']?\s*:\s*(\d+)', text)]
        report["rankings"] = [{"resume_id": i, "grade": "B", "rank": n + 1, "comment": "可以面"}
                              for n, i in enumerate(ids)]
        content = report
    return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
