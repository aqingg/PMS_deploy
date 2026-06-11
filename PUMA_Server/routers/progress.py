from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import crud, schemas
from database import get_db

router = APIRouter(prefix="/progress", tags=["Project Progress API"])


@router.post("/", response_model=schemas.DepartmentProgress)
def create(data: schemas.DepartmentProgressCreate, db: Session = Depends(get_db)):
    return crud.create_progress(db, data)


@router.get("/{project_id}", response_model=list[schemas.DepartmentProgress])
def get_by_project(project_id: int, db: Session = Depends(get_db)):
    return crud.get_progress_by_project(db, project_id)
