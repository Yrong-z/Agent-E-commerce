"""本地部署静态页面：保留 API/文档，缺失资源不回退成页面。"""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from app.config import PROJECT_ROOT
from app.schemas import DomainError


def mount_frontend(app: FastAPI, directory: Path | None = None) -> None:
    root = (directory or PROJECT_ROOT / 'web/dist').resolve()
    index = root / 'index.html'
    if not index.is_file():
        raise RuntimeError('前端生产构建缺失，请从根目录重新运行 start.cmd')

    @app.api_route('/{path:path}', methods=['GET', 'HEAD'], include_in_schema=False)
    async def frontend(request: Request, path: str):
        # 保留命名空间与缺失文件错误，防止 SPA 掩盖 API、文档或资源错误。
        target = (root / path).resolve()
        reserved = path.split('/')[0] in {'api', 'docs', 'redoc', 'openapi.json', 'assets', 'products'}
        hidden = any(part.startswith('.') for part in path.split('/') if part)
        if hidden or not target.is_relative_to(root) or (reserved and path.split('/')[0] in {'api', 'docs', 'redoc', 'openapi.json'}):
            raise DomainError('NOT_FOUND', '请求路径不存在', 404)
        if target.is_file():
            return FileResponse(target, headers={'Cache-Control': 'no-cache'})
        if reserved or Path(path).suffix:
            raise DomainError('NOT_FOUND', '请求资源不存在', 404)
        return FileResponse(index, headers={'Cache-Control': 'no-cache'})
