from fastapi import APIRouter
import json
from utils.file_loader import load_template

router = APIRouter(
    prefix="/user",
    tags=["User Authorization API"]
)

@router.get("/checkUser/{username}")
def check_user(username: str):
    try:
        data = load_template("Authorized.json")
    except Exception:
        return {"username": username, "department": "unknown"}

    users = data.get("authorized_users", [])

    # 遍历匹配用户
    for user in users:
        if user.get("username") == username:
            return {
                "username": username,
                "department": user.get("department")
            }

    # 没找到用户 → 返回 unknown
    return {
        "username": username,
        "department": "unknown"
    }
