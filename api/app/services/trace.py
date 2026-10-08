"""脱敏的必要执行摘要；不记录密钥、请求头或隐藏推理。"""
from psycopg.types.json import Jsonb
from datetime import datetime, timezone
from urllib.parse import urlsplit
import httpx
from app.db import get_connection
from app.schemas import TraceEvent, CapabilityStatus
from app.schemas import DemoStatus, ServiceStatus, ExecutionRecord, ExecutionStep
from app.config import get_settings
from app.services import knowledge
from app.agent.state import load_session

async def record_trace_event(event: TraceEvent) -> None:
    """记录参数/结果摘要、工具耗时和明确错误码。"""
    event.checked_at = datetime.now(timezone.utc)
    async with get_connection() as connection:
        await connection.execute('INSERT INTO traces(request_id,payload) VALUES (%s,%s)',(event.request_id,Jsonb(event.model_dump(mode='json'))))

async def get_request_trace(request_id: str) -> list[TraceEvent]:
    """按执行顺序读取必要记录，不包含模型内部思考。"""
    async with get_connection() as connection:
        cursor = await connection.execute('SELECT payload FROM traces WHERE request_id=%s ORDER BY id',(request_id,))
        return [TraceEvent.model_validate(row[0]) for row in await cursor.fetchall()]

async def get_capability_status() -> list[CapabilityStatus]:
    """能力验证登记仍待后续，不以存在代码宣称在线通过。"""
    raise NotImplementedError('能力记录尚未实现')

async def get_demo_status(session_id: str | None = None) -> DemoStatus:
    """读取实际状态与最近会话摘要；只探测本地健康，不调用模型。"""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    def status(value, detail, checked_at=now):
        return ServiceStatus(status=value, detail=detail, checked_at=checked_at)
    result = DemoStatus(backend=status('available','HTTP 已响应'), database=status('unavailable','数据库暂不可用'),
        embedding=status('not_checked','尚未检查',None), chat=status('not_checked','暂无带时间的模型调用记录',None),
        chat_model=settings.chat_model or '未配置', embedding_model=settings.embedding_model,
        embedding_dimension=settings.embedding_dimension, sources=[], document_count=0, chunk_count=0, corpus_models=[], executions=[])
    try:
        result.sources = await knowledge.list_sources()
        result.document_count = len(result.sources)
        result.chunk_count = sum(source.chunk_count for source in result.sources)
        async with get_connection() as connection:
            cursor = await connection.execute('SELECT DISTINCT embedding_model,embedding_dimension FROM knowledge_chunks WHERE source_owner=%s',(knowledge.SOURCE_OWNER,))
            result.corpus_models = [{'model':row[0],'dimension':row[1]} for row in await cursor.fetchall()]
            cursor = await connection.execute("SELECT t.payload FROM traces t WHERE t.payload->>'tool_name'='model' AND EXISTS (SELECT 1 FROM sessions s, jsonb_each(s.state->'response_cache') c WHERE s.customer_id=%s AND c.value->'response'->>'request_id'=t.request_id) ORDER BY t.id DESC LIMIT 1",(settings.demo_customer_id,))
            row = await cursor.fetchone()
        result.database = status('available','数据库读取成功')
        if row:
            event = TraceEvent.model_validate(row[0])
            if event.checked_at:
                result.chat = status('unavailable' if event.error else 'available','最近一次模型调用：'+(event.error or '成功'),event.checked_at)
    except Exception:
        result.sources=[]; result.document_count=0; result.chunk_count=0; result.corpus_models=[]
    if urlsplit(settings.embedding_base_url).hostname in {'127.0.0.1','localhost','::1'}:
        try:
            async with httpx.AsyncClient(trust_env=False,timeout=3) as client:
                response = await client.get(settings.embedding_base_url.rstrip('/').removesuffix('/v1')+'/health')
            result.embedding=status('available' if response.status_code==200 else 'unavailable','本地 TEI 健康检查：HTTP '+str(response.status_code))
        except Exception:
            result.embedding=status('unavailable','本地向量服务无法连接；可显式重试')
    else:
        result.embedding=status('not_checked','非本地服务未发起额外探测',None)
    if session_id and result.database.status=='available':
        session = await load_session(session_id,settings.demo_customer_id)
        cached = sorted(session.response_cache.values(),key=lambda item:item.get('cached_at',''),reverse=True)[:10]
        for item in cached:
            response = item['response']
            events = await get_request_trace(response['request_id'])
            result.executions.append(ExecutionRecord(request_id=response['request_id'],status=response['status'],checked_at=item.get('cached_at'),
                steps=[ExecutionStep(tool_name=e.tool_name,duration_ms=e.duration_ms,error=e.error,checked_at=e.checked_at,sources=e.sources) for e in events]))
    return result
