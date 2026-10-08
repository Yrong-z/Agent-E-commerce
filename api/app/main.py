"""应用装配、生命周期和统一错误响应。"""
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app import db
from app.config import get_settings
from app.schemas import ApiError, DomainError
from app.routes import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理连接池并初始化空表；数据库故障不阻止诊断接口。"""
    get_settings()
    await db.open_pool()
    try:
        try:
            await db.init_schema()
        except Exception:
            pass  # 健康接口实时报告故障，不打印凭据或连接错误文本
        yield
    finally:
        await db.close_pool()

def create_app() -> FastAPI:
    """创建框架应用并挂载文档约定路由。"""
    app = FastAPI(title='选购助手', version='0.1.0', lifespan=lifespan)
    @app.middleware('http')
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        return response
    @app.exception_handler(NotImplementedError)
    async def not_implemented(request: Request, exc: NotImplementedError):
        error = ApiError(code='NOT_IMPLEMENTED', message='该业务尚未实现', request_id=request.state.request_id)
        return JSONResponse(status_code=501, content=error.model_dump())
    @app.exception_handler(RequestValidationError)
    async def invalid_argument(request: Request, exc: RequestValidationError):
        error = ApiError(code='INVALID_ARGUMENT', message='请求参数不符合接口契约', request_id=request.state.request_id)
        return JSONResponse(status_code=422, content=error.model_dump())
    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        error = ApiError(code=exc.code, message=exc.message, retryable=exc.status_code>=500, request_id=request.state.request_id)
        return JSONResponse(status_code=exc.status_code, content=error.model_dump())
    app.include_router(router, prefix='/api')
    if get_settings().serve_frontend:
        from app.frontend import mount_frontend
        mount_frontend(app)
    return app

app = create_app()
