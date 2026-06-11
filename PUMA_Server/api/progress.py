from fastapi import APIRouter

router = APIRouter(
    prefix="/progress",
    tags=["Progress API"]
)

# GET /progress/{project_id}
@router.get("/{project_id}")
def get_progress(project_id: int):
    return {
        "project_id": project_id,
        "progress": [
            {"department": "R&D", "progress": 70},
            {"department": "Purchase", "progress": 40}
        ]
    }

# POST /progress/update
@router.post("/update")
def update_progress(progress_data: dict):
    return {
        "message": "Progress updated (dummy)",
        "received": progress_data
    }
