import io
import re
import zipfile
from typing import List

from fastapi import (
    FastAPI,
    Response,
    HTTPException,
    Path as FastApiPath,
    Query,
    UploadFile,
    File,
    Form
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from logic import (
    fetch_project_identifiers,
    fetch_single_project_details,
    fetch_all_project_details,
)
from util import (
    merge_and_fill_excel,
    fill_excel_by_placeholders,
    fill_docx_by_placeholders,
    fill_pptx_by_placeholders
)
import pcminfo_pb2

app = FastAPI(
    title="Project Data API",
    description="An API to fetch and consolidate project data, served via Protobuf or Excel.",
    version="2.0.0",
    openapi_prefix="/temp",
)

origins = [
    "https://pages.github.boschdevcloud.com",
    "http://localhost",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:7175",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PROTOBUF_MEDIA_TYPE = "application/x-protobuf"
ZIP_MEDIA_TYPE = "application/zip"

@app.get(
    "/api/v1/identifiers",
    response_class=Response,
    responses={
        200: {"content": {PROTOBUF_MEDIA_TYPE: {}}, "description": "Success"},
        500: {"description": "Failed to fetch initial project list"},
    },
    summary="Get All Project Identifiers (Protobuf)",
    tags=["Projects"]
)
async def get_identifiers():
    """
    Fetches a lightweight list of all matching projects, returning only their
    UUID and customer name in Protobuf format.
    """
    try:
        identifiers  = await fetch_project_identifiers()
        
        proto_response = pcminfo_pb2.ProjectIdentifierList()
        for item in identifiers :
            if item.get("uuid") and item.get("customer"):
                proto_id = proto_response.identifiers.add()
                proto_id.uuid = item["uuid"]
                proto_id.customer = item["customer"]

        serialized_data = proto_response.SerializeToString()
        return Response(content=serialized_data, media_type=PROTOBUF_MEDIA_TYPE)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch identifiers: {e}")


@app.post(
    "/api/v1/projects/documents",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "成功。返回包含已填充数据的文件的ZIP压缩包。",
            "content": { ZIP_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        },
        400: {"description": "没有提供文件、UUID或文件处理失败"},
        404: {"description": "未找到具有给定UUID的项目"},
        500: {"description": "内部服务器错误"},
    },
    summary="上传、填充并下载项目文档",
    tags=["Projects"]
)
async def process_and_download_documents(
    uuid: str = Form(..., description="要填充数据的项目的UUID。"),
    files: List[UploadFile] = File(..., description="一个或多个要填充数据的模板文件 (Excel, Word, PowerPoint)。")
):
    """
    接收一个UUID和一个或多个模板文件。使用指定UUID的项目数据填充文件，
    然后将所有处理过的文件打包成一个ZIP压缩包返回。
    支持 .xlsx, .xlsm, .docx, .docm, .pptx 文件。
    """
    if not files:
        raise HTTPException(status_code=400, detail="没有提供任何文件。")
    if not uuid:
        raise HTTPException(status_code=400, detail="没有提供项目UUID。")

    try:
        profile_dict = await fetch_single_project_details(uuid)
        if not profile_dict:
            raise HTTPException(status_code=404, detail=f"无法检索到项目UUID '{uuid}' 的详细信息。")

        zip_stream = io.BytesIO()
        with zipfile.ZipFile(zip_stream, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for uploaded_file in files:
                filename = uploaded_file.filename.lower()
                modified_stream = None

                file_content = await uploaded_file.read()
                file_stream = io.BytesIO(file_content)

                if filename.endswith(('.xlsx', '.xlsm')):
                    modified_stream = fill_excel_by_placeholders(profile_dict, file_stream)
                elif filename.endswith(('.docx', '.docm')):
                    modified_stream = fill_docx_by_placeholders(profile_dict, file_stream)
                elif filename.endswith('.pptx'):
                    modified_stream = fill_pptx_by_placeholders(profile_dict, file_stream)
                else:
                    print(f"警告: 跳过不支持的文件类型: {uploaded_file.filename}")
                    continue

                if modified_stream:
                    zipf.writestr(uploaded_file.filename, modified_stream.read())
        
        zip_stream.seek(0)

        customer_name = re.sub(r'[^\w\-_\. ]', '_', profile_dict.get("customer", "Unknown"))
        project_name = re.sub(r'[^\w\-_\. ]', '_', profile_dict.get("project", "Project"))
        zip_filename = f"Processed_Documents_{customer_name}_{project_name}.zip"
        
        headers = {'Content-Disposition': f'attachment; filename="{zip_filename}"'}

        return StreamingResponse(
            content=zip_stream,
            media_type=ZIP_MEDIA_TYPE,
            headers=headers
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"发生内部错误: {e}")


@app.get(
    "/api/v1/projects/info/{uuid}",
    response_class=Response,
    responses={
        200: {"content": {PROTOBUF_MEDIA_TYPE: {}}, "description": "Success"},
        500: {"description": "Failed to fetch initial project information"},
    },
    summary="Get  Project Information (Protobuf)",
    tags=["Projects"]
)
async def get_information_by_uuid(uuid: str):
    try:
        information_dict = await fetch_single_project_details(uuid)

        proto_message = pcminfo_pb2.ProjectProfile(**information_dict)
        serialized_content = proto_message.SerializeToString()
        
        return Response(content=serialized_content, media_type=PROTOBUF_MEDIA_TYPE)
    except HTTPException as e:
        raise e
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"发生内部错误: {e}")


@app.post(
    "/api/v1/projects/merge-and-fill",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "成功。返回一个已合并和填充的 Excel 文件。",
            "content": { EXCEL_MEDIA_TYPE: {}},
        },
        400: {"description": "未提供必要的文件或UUID，或文件处理失败。"},
        404: {"description": "未找到具有给定UUID的项目。"},
        500: {"description": "内部服务器错误。"},
    },
    summary="合并、填充并返回单个Excel文件",
    tags=["Projects"]
)
async def merge_and_fill_document(
    uuid: str = Form(..., description="用于填充 <PMS> 占位符的项目的UUID。"),
    template_file: UploadFile = File(..., alias="template", description="包含 <PMS> 占位符和需要被替换区域的模板Excel文件。"),
    base_file: UploadFile = File(..., alias="base", description="包含完整数据的源Excel文件，用于替换模板中的非占位符区域。")
):
    if not all([uuid, template_file, base_file]):
        raise HTTPException(status_code=400, detail="必须同时提供 'uuid', 'template' 和 'base' 文件。")

    try:
        # 1. 获取项目数据用于填充占位符
        profile_dict = await fetch_single_project_details(uuid)
        if not profile_dict:
            raise HTTPException(status_code=404, detail=f"无法检索到项目UUID '{uuid}' 的详细信息。")

        # 2. 读取上传文件的内容到内存流
        template_content = await template_file.read()
        base_content = await base_file.read()

        template_stream = io.BytesIO(template_content)
        base_stream = io.BytesIO(base_content)

        # 3. 调用核心逻辑函数，执行合并与填充
        modified_stream = merge_and_fill_excel(profile_dict, template_stream, base_stream)
        
        # 4. 准备下载的文件名和响应头
        output_filename = f"filled_merged_{template_file.filename}"
        headers = {'Content-Disposition': f'attachment; filename="{output_filename}"'}
        
        # 5. 以文件流形式返回结果
        return StreamingResponse(
            content=modified_stream,
            media_type=EXCEL_MEDIA_TYPE,
            headers=headers
        )

    except HTTPException as e:
        # 重新抛出已知的HTTP异常
        raise e
    except Exception as e:
        # 捕获其他意外错误
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"发生内部错误: {e}")


@app.get("/", include_in_schema=False)
def read_root():
    return {"message": "Welcome to the Project Data API. Visit /docs for the API documentation."}
