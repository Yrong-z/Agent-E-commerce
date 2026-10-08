"""静态托管边界：真实文件、SPA刷新、保留路径及越界防护。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from app.frontend import mount_frontend
from app.schemas import DomainError


def test_hosting_boundaries(tmp_path):
    (tmp_path / 'index.html').write_text('<html>实际构建入口</html>', encoding='utf-8')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/app.js').write_text('export const ready=true', encoding='utf-8')
    (tmp_path / '.env').write_text('仅测试占位配置', encoding='utf-8')
    app = FastAPI()
    @app.exception_handler(DomainError)
    async def error(request, exc):
        return JSONResponse({'code': exc.code}, status_code=exc.status_code)
    @app.get('/api/health')
    def health():
        return {'status': 'ok'}
    mount_frontend(app, tmp_path)
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert '实际构建入口' in client.get('/shopping/session').text
        assert client.get('/api/health').json() == {'status': 'ok'}
        assert client.get('/assets/app.js').text == 'export const ready=true'
        assert client.get('/docs').status_code == client.get('/openapi.json').status_code == 200
        for path in ('/api/missing', '/assets/missing.js', '/products/missing.svg', '/missing.css', '/docs/missing', '/%2E%2E/config.py', '/.env', '/%2Eenv', '/.git/config', '/shopping/.private'):
            response = client.get(path)
            assert response.status_code == 404 and response.json()['code'] == 'NOT_FOUND'
        assert client.post('/api/missing').status_code in (404, 405)


def test_missing_build_is_explicit(tmp_path):
    with pytest.raises(RuntimeError, match='生产构建缺失'):
        mount_frontend(FastAPI(), tmp_path)
