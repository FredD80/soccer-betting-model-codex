from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.models import Performance, ModelVersion
from api.deps import get_session
from api.schemas import ModelPerformanceResponse

router = APIRouter()


@router.get("", response_model=list[ModelPerformanceResponse])
def model_performance(session: Session = Depends(get_session)):
    rows = session.query(Performance).all()
    result = []
    for row in rows:
        mv = session.query(ModelVersion).filter_by(id=row.model_id).first()
        result.append(ModelPerformanceResponse(
            model_name=mv.name if mv else "unknown",
            version=mv.version if mv else "unknown",
            bet_type=row.bet_type,
            total_predictions=row.total_predictions or 0,
            correct=row.correct or 0,
            accuracy=row.accuracy or 0.0,
            roi=row.roi or 0.0,
        ))
    return result
