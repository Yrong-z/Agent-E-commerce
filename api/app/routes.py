"""HTTP 入口；商品/订单已联通业务服务，其余明确返回 501。"""
from fastapi import APIRouter, Query, Request, Path
from fastapi.responses import JSONResponse
from app import db
from app.schemas import *
from app.config import get_settings
from app.services import catalog, orders, knowledge, after_sales
from app.services.trace import get_request_trace, record_trace_event, get_demo_status
from app.agent import state
from app.agent.runtime import run_agent_turn, REQUEST_TIMEOUT_SECONDS
import asyncio
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid5, NAMESPACE_URL

router = APIRouter(responses={404: {'model': ApiError}, 501: {'model': ApiError}, 422: {'model': ApiError}})

@router.get('/demo/status', response_model=DemoStatus)
async def demo_status(session_id: str | None = Query(default=None, min_length=1, max_length=100)) -> DemoStatus:
    """只读状态和当前用户会话摘要，不发起收费模型请求。"""
    return await get_demo_status(session_id)

@router.get('/health', response_model=HealthResponse, responses={503: {'model': HealthResponse}})
async def health():
    """检查应用、数据库和 pgvector，不调用模型。"""
    try:
        database, vector = await db.check_database()
    except Exception:
        database, vector = False, False
    settings = get_settings()
    configured = bool(settings.chat_base_url and settings.chat_model and settings.chat_api_key.get_secret_value())
    result = HealthResponse(status='ok' if database and vector else 'degraded', database='ok' if database else 'unavailable', pgvector='ok' if vector else 'unavailable', chat_model='configured' if configured else 'not_configured', detail='基础设施就绪' if database and vector else '数据库或 pgvector 未就绪；请检查 Docker 和本地配置')
    return JSONResponse(status_code=200 if database and vector else 503, content=result.model_dump())

@router.post('/chat', response_model=ChatResponse)
async def chat(body: ChatRequest, http_request: Request) -> ChatResponse:
    """同会话串行与近期请求去重；新会话重试使用稳定 ID。"""
    customer_id = get_settings().demo_customer_id
    session_id = body.session_id or str(uuid5(NAMESPACE_URL,customer_id+':'+body.client_message_id))
    started = monotonic()
    processing_budget = max(0,REQUEST_TIMEOUT_SECONDS-2)  # 留两秒落库整体超时事件。
    if not body.message.strip():
        raise DomainError('INVALID_ARGUMENT','消息不能为空白',422)
    try:
        async with asyncio.timeout(processing_budget):
            async with state.session_lock(session_id,customer_id):
                try:
                    session = await state.load_session(session_id,customer_id)
                except DomainError:
                    if body.session_id:
                        raise
                    session = SessionState(session_id=session_id,updated_at=datetime.now(timezone.utc))
                    await state.save_session(session,customer_id)
                cached = session.response_cache.get(body.client_message_id)
                if cached:
                    if cached['message']!=body.message:
                        raise DomainError('MESSAGE_ID_CONFLICT','该消息 ID 已用于不同内容',409)
                    return ChatResponse.model_validate(cached['response'])
                response = await run_agent_turn(body,session,request_id=http_request.state.request_id,timeout_seconds=max(0,processing_budget-(monotonic()-started)))
                session.response_cache[body.client_message_id] = {'message':body.message,'response':response.model_dump(mode='json'),'cached_at':datetime.now(timezone.utc).isoformat()}
                # PostgreSQL jsonb 不保留对象插入顺序，按时间裁剪才是最近二十条。
                session.response_cache = dict(sorted(session.response_cache.items(),key=lambda item:item[1].get('cached_at',''))[-20:])
                await state.save_session(session,customer_id,allow_create=False)
                return response
    except TimeoutError:
        try:
            async with asyncio.timeout(2):
                await record_trace_event(TraceEvent(request_id=http_request.state.request_id,tool_name='agent',arguments_summary='同会话等待/有限处理',result_summary='整体超时；未完成',duration_ms=int((monotonic()-started)*1000),error='REQUEST_TIMEOUT'))
        except Exception:
            pass  # 数据库不可用时仍返回明确失败，不泄露异常或伪造记录。
        raise DomainError('REQUEST_TIMEOUT','会话整体请求超时，本次未完成，请重试',504) from None

@router.get('/sessions', response_model=list[SessionSummary])
async def list_sessions() -> list[SessionSummary]:
    """当前顾客最近二十个实际会话。"""
    return await state.list_customer_sessions(get_settings().demo_customer_id)

@router.get('/sessions/page', response_model=SessionPage)
async def page_sessions(offset: int = Query(default=0,ge=0), limit: int = Query(default=20,ge=1,le=50)):
    """管理摘要分页，不返回聊天正文；侧栏仍用原二十条入口。"""
    return await state.page_customer_sessions(get_settings().demo_customer_id,offset,limit)

@router.post('/sessions/delete', response_model=SessionDeletionResult)
async def delete_sessions(body: DeleteSessionsRequest):
    """原子批量删除，服务端绑定顾客、去重及忙碌保护。"""
    return await state.delete_customer_sessions(get_settings().demo_customer_id,body.session_ids)

@router.delete('/sessions', response_model=SessionDeletionResult)
async def delete_all_sessions(body: DeleteAllSessionsRequest):
    """删除当前顾客所有会话；确认数量变化返回冲突，不缩成当前页。"""
    return await state.delete_customer_sessions(get_settings().demo_customer_id,expected_count=body.expected_count)

@router.delete('/sessions/{session_id}', response_model=SessionDeletionResult)
async def delete_session(session_id: str = Path(min_length=1,max_length=100)):
    """单条删除；不存在或其他顾客ID均只报告未找到。"""
    if not session_id.strip():
        raise DomainError('INVALID_ARGUMENT','会话 ID 不能为空白',422)
    return await state.delete_customer_sessions(get_settings().demo_customer_id,[session_id])

@router.post('/sessions', response_model=SessionResponse)
async def create_session() -> SessionResponse:
    """手动售后建立空会话，无在线模型调用。"""
    from uuid import uuid4
    session = SessionState(session_id=str(uuid4()),updated_at=datetime.now(timezone.utc))
    customer_id = get_settings().demo_customer_id
    async with state.session_lock(session.session_id,customer_id):
        await state.save_session(session,customer_id)
    return SessionResponse(state=session,view_state=session.view_state)

@router.get('/sessions/{session_id}', response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """恢复工具事实快照和显示消息，内部去重缓存不传前端。"""
    session = await state.load_session(session_id,get_settings().demo_customer_id)
    return SessionResponse(state=session.model_copy(update={'response_cache':{}}),view_state=session.view_state)

@router.get('/products', response_model=list[Product])
async def list_products(query: str = '', budget_max_fen: int | None = Query(default=None, ge=0), use_case: str | None = None, in_stock_only: bool = True, limit: int = Query(default=6, ge=1, le=6)) -> list[Product]:
    """筛选数据库商品，预算单位为分。"""
    return await catalog.search_products(query, budget_max_fen, use_case, in_stock_only, limit)

@router.post('/products/compare', response_model=Comparison)
async def compare_products_route(body: CompareProductsRequest) -> Comparison:
    """比较两款已存在的不同商品。"""
    return await catalog.compare_products(body.product_ids)

@router.get('/products/{product_id}', response_model=Product)
async def product_detail(product_id: str) -> Product:
    """读取商品参数和同源计算价格。"""
    return await catalog.get_product(product_id)

@router.get('/orders', response_model=list[Order])
async def list_orders() -> list[Order]:
    """查询配置指定的演示顾客已有订单。"""
    return await orders.list_customer_orders(get_settings().demo_customer_id)

@router.get('/orders/{order_id}', response_model=Order)
async def order_detail(order_id: str) -> Order:
    """查询当前顾客订单及物流，未知或其他顾客订单返回 404。"""
    return await orders.get_order(order_id, get_settings().demo_customer_id)

@router.post('/after-sales/preview', response_model=AfterSalesPreview)
async def preview_after_sales_route(body: PreviewAfterSalesRequest) -> AfterSalesPreview:
    """建立十分钟模拟售后预览。"""
    async with state.session_lock(body.session_id,get_settings().demo_customer_id):
        return await after_sales.prepare_after_sales(body.order_id,body.reason,body.session_id,get_settings().demo_customer_id)

@router.post('/after-sales/{preview_id}/confirm', response_model=AfterSalesPreview)
async def confirm_after_sales_route(preview_id: str, body: SessionActionRequest) -> AfterSalesPreview:
    """事务内显式确认；不注册到模型工具。"""
    async with state.session_lock(body.session_id,get_settings().demo_customer_id):
        return await after_sales.confirm_after_sales(preview_id,body.session_id,get_settings().demo_customer_id)

@router.post('/after-sales/{preview_id}/cancel', response_model=AfterSalesPreview)
async def cancel_after_sales_route(preview_id: str, body: SessionActionRequest) -> AfterSalesPreview:
    """取消待确认预览。"""
    async with state.session_lock(body.session_id,get_settings().demo_customer_id):
        return await after_sales.cancel_after_sales(preview_id,body.session_id,get_settings().demo_customer_id)

@router.get('/after-sales', response_model=list[AfterSalesPreview])
async def list_after_sales() -> list[AfterSalesPreview]:
    """当前用户售后记录列表。"""
    return await after_sales.list_after_sales(get_settings().demo_customer_id)

@router.get('/after-sales/{preview_id}', response_model=AfterSalesPreview)
async def after_sales_detail(preview_id: str):
    return await after_sales.get_after_sales(preview_id,get_settings().demo_customer_id)

@router.get('/knowledge/sources', response_model=list[KnowledgeSource])
async def list_knowledge_sources() -> list[KnowledgeSource]:
    """实际已入库资料列表。"""
    return await knowledge.list_sources()

@router.get('/traces/{request_id}', response_model=list[TraceEvent])
async def get_trace(request_id: str) -> list[TraceEvent]:
    """一次请求的必要执行摘要；不存在时明确失败。"""
    events = await get_request_trace(request_id)
    if not events:
        raise DomainError('TRACE_NOT_FOUND','未找到该执行记录')
    return events

@router.get('/evaluations/latest', response_model=EvalReport)
async def get_eval_report() -> EvalReport:
    """最近评测，尚未实现；文件状态另记 not_run。"""
    raise NotImplementedError

@router.get('/capabilities', response_model=list[CapabilityStatus])
async def get_capabilities() -> list[CapabilityStatus]:
    """能力状态接口，尚未实现。"""
    raise NotImplementedError
