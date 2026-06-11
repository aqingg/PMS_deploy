from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import crud, schemas
from database import get_db

router = APIRouter(prefix="/project", tags=["Project API"])


@router.post("/", response_model=schemas.Project)
def create(data: schemas.ProjectCreate, db: Session = Depends(get_db)):
    return crud.create_project(db, data)


@router.get("/", response_model=list[schemas.Project])
def get_all(db: Session = Depends(get_db)):
    return crud.get_projects(db)
