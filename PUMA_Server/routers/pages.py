from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
import crud

router = APIRouter()

templates = Jinja2Templates(directory="templates")


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    projects = crud.get_projects(db)
    return templates.TemplateResponse("index.html", {"request": request, "projects": projects})
