# main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.database import engine, Base

# Routers
from api import project as project_api
from api import user as user_api
from api import progress as progress_api
from api import templates as templates_api
# from api import todo as todo_api
from api import download
from api import pms
from api import events
from api import report
from api import IAR_report
from api.sse_stream import router as sse_stream_router
from api.todo_v2 import router as todo_v2_router
from api import database as database_api
from api import TCD09_report


# =====================================================
# 初始化数据库（必须放在 app 前）
# =====================================================
Base.metadata.create_all(bind=engine)

# =====================================================
# 创建 FastAPI 应用（带 root_path）
# =====================================================
# ⭐ 很关键：root_path 会让所有路由挂在 /app-puma 下
# 例如 /project/listProjects → 实际路径是 /app-puma/project/listProjects
app = FastAPI(root_path="/app-puma")

# =====================================================
# CORS（非常重要）
# =====================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8088",
        "http://localhost:3000",
        "http://localhost:3001",
        "https://cccn.apac.bosch.com",
        "https://cccn.apac.bosch.com/APP-PMS-GATE",
        "https://cccn.apac.bosch.com/APP-PMS-Project",
        "https://oss-dthub.apac.bosch.com/temp",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================
# 注册所有 Routers（不要 prefix，除 SSE 外）
# =====================================================
# ⭐ root_path 会自动把这些路由放到 /app-puma 下，无需 prefix="/app-puma"
app.include_router(project_api.router)
app.include_router(progress_api.router)
app.include_router(templates_api.router)
app.include_router(user_api.router)
app.include_router(download.router)
app.include_router(pms.router)
app.include_router(events.router)
app.include_router(report.router)
app.include_router(IAR_report.router)
app.include_router(todo_v2_router)
app.include_router(TCD09_report.router)


# ⭐ SSE 独立路由
app.include_router(sse_stream_router, prefix="/sse")
app.include_router(database_api.router)

# =====================================================
# 本地启动
# =====================================================
import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8086, reload=True)
