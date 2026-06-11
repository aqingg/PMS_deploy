from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from models.database import engine, Base

# Routers
from api import project as project_api
from api import user as user_api
from api import progress as progress_api
from api import templates as templates_api
from api import download
from api import pms
from api import events
from api import report
from api.sse_stream import router as sse_stream_router
from api.todo_v2 import router as todo_v2_router
from api import database as database_api

# =====================================================
# Database init (must be before app creation)
# =====================================================
Base.metadata.create_all(bind=engine)

# =====================================================
# FastAPI app
# =====================================================
# root_path means external paths are under /app-puma/...
app = FastAPI(root_path="/app-puma")

# =====================================================
# CORS
# =====================================================
# IMPORTANT: allow_origins must contain pure origins only (no path suffix)
ALLOWED_ORIGINS = [
    "http://localhost:8088",
    "http://localhost:3000",
    "http://localhost:3001",
    "https://cccn.apac.bosch.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)

# Optional lightweight debug logs for CORS triage
CORS_DEBUG = True


@app.middleware("http")
async def cors_debug_middleware(request: Request, call_next):
    response = await call_next(request)

    if CORS_DEBUG:
        origin = request.headers.get("origin")
        acrm = request.headers.get("access-control-request-method")
        acrh = request.headers.get("access-control-request-headers")
        print(
            f"[CORS] method={request.method} path={request.url.path} "
            f"origin={origin} acrm={acrm} acrh={acrh} status={response.status_code}"
        )

    return response


# Optional explicit OPTIONS fallback for proxies that behave oddly on preflight
@app.options("/{full_path:path}")
async def preflight_handler(full_path: str, request: Request):
    origin = request.headers.get("origin")
    headers = {}

    if origin in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        headers["Access-Control-Allow-Headers"] = request.headers.get(
            "access-control-request-headers", "*"
        )

    return Response(status_code=200, headers=headers)


# =====================================================
# Routers
# =====================================================
app.include_router(project_api.router)
app.include_router(progress_api.router)
app.include_router(templates_api.router)
app.include_router(user_api.router)
app.include_router(download.router)
app.include_router(pms.router)
app.include_router(events.router)
app.include_router(report.router)
app.include_router(todo_v2_router)
app.include_router(sse_stream_router, prefix="/sse")
app.include_router(database_api.router)

# =====================================================
# Local startup
# =====================================================
import uvicorn

if __name__ == "__main__":
    uvicorn.run("main2:app", host="0.0.0.0", port=8086, reload=True)
