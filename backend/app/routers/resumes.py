from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Resume

router = APIRouter(prefix="/api")


@router.get("/resumes/{resume_id}/report")
def resume_report(resume_id: int, db: Session = Depends(get_db)):
    r = db.get(Resume, resume_id)
    if not r:
        raise HTTPException(404, "简历不存在")
    return {
        "id": r.id,
        "filename": r.filename,
        "status": r.status,
        "parse_meta": r.parse_meta,
        "raw_text": r.raw_text,
        "profile": r.profile,
        "screening": r.screening,
        "evaluation": r.evaluation,
        "final_grade": r.final_grade,
        "final_rank": r.final_rank,
        "error_message": r.error_message,
    }
