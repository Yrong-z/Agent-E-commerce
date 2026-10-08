"""O2 已启动真实 API 的必要参数错误断言，不覆盖尚未实现售后。"""
import httpx
import pytest

@pytest.mark.parametrize('method,path,body', [
    ('GET', '/products?budget_max_fen=-1', None),
    ('GET', '/products?limit=7', None),
    ('POST', '/products/compare', {'product_ids':['DEMO-A1','DEMO-A1']}),
])
def test_invalid_catalog_request(method, path, body):
    """验证 HTTP 边界拒绝无效预算、数量上限和重复比较 ID。"""
    with httpx.Client(base_url='http://127.0.0.1:8000/api', timeout=10) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 422
    error = response.json()
    assert error['code'] == 'INVALID_ARGUMENT' and error['request_id']


def test_sessions_restore_idempotency_conflict_and_concurrency(monkeypatch):
    """真实数据库/ASGI，模型夹具仅验证保存、归属、同会话串行和去重。"""
    import asyncio
    from uuid import uuid4
    from app import db,routes
    from app.main import app
    from app.config import get_settings
    from app.schemas import ChatResponse,DomainError
    from app.agent.tools import LocalToolExecutor
    executions=[]; session_ids=set()
    async def offline_turn(request,session,**kwargs):
        executions.append(1)
        await asyncio.sleep(0.02)
        result=await LocalToolExecutor().execute('search_products',{'budget_max_fen':30000,'use_case':'通勤','limit':2},session)
        session.display_messages=[{'role':'user','content':request.message},{'role':'assistant','content':'离线会话保存夹具'}]
        return ChatResponse(request_id=str(uuid4()),session_id=session.session_id,answer='离线会话保存夹具',status='completed',view_state=result.view_updates)
    monkeypatch.setattr(routes,'run_agent_turn',offline_turn)
    async def check():
        await db.open_pool()
        customer=get_settings().demo_customer_id
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                body={'message':'离线幂等验证','client_message_id':str(uuid4())}
                first,duplicate=await asyncio.gather(client.post('/api/chat',json=body),client.post('/api/chat',json=body))
                assert first.status_code==duplicate.status_code==200 and first.json()==duplicate.json() and len(executions)==1
                id=first.json()['session_id']; session_ids.add(id)
                restored=await client.get('/api/sessions/'+id)
                assert restored.status_code==200 and restored.json()['view_state']==first.json()['view_state']
                assert restored.json()['state']['candidate_product_ids']==['DEMO-A1','DEMO-B2']
                assert restored.json()['state']['response_cache']=={}
                body['session_id']=id
                assert (await client.post('/api/chat',json=body)).json()==first.json() and len(executions)==1
                body['message']='不同内容'
                conflict=await client.post('/api/chat',json=body)
                assert conflict.status_code==409 and conflict.json()['code']=='MESSAGE_ID_CONFLICT'
                assert any(s['session_id']==id for s in (await client.get('/api/sessions')).json())
                from app.agent.state import load_session
                with pytest.raises(DomainError): await load_session(id,'different-customer')
                assert (await client.get('/api/sessions/nonexistent')).status_code==404
                # jsonb 会重排对象键；缓存裁剪必须按时间，不依赖字典插入顺序。
                from app.agent.state import save_session
                stored=await load_session(id,customer)
                oldest='z'*45
                stored.response_cache={oldest:{'message':'旧夹具','response':first.json(),'cached_at':'2020-01-01T00:00:00Z'},**{f'a-{i:02d}':{'message':'夹具','response':first.json(),'cached_at':f'2020-01-02T00:00:{i:02d}Z'} for i in range(19)}}
                await save_session(stored,customer)
                latest=str(uuid4())
                assert (await client.post('/api/chat',json={'session_id':id,'message':'缓存时间窗口','client_message_id':latest})).status_code==200
                stored=await load_session(id,customer)
                assert len(stored.response_cache)==20 and latest in stored.response_cache and oldest not in stored.response_cache
        finally:
            async with db.get_connection() as connection:
                for id in session_ids: await connection.execute('DELETE FROM sessions WHERE session_id=%s AND customer_id=%s',(id,customer))
            await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)


def test_request_deadline_records_failure_without_fake_success(monkeypatch):
    """整体预算含同会话等待，超时有真实 trace；仅使用临时测试会话。"""
    import asyncio
    from uuid import uuid4,uuid5,NAMESPACE_URL
    from app import db,routes
    from app.main import app
    from app.config import get_settings
    customer=get_settings().demo_customer_id
    message_id=str(uuid4()); session_id=str(uuid5(NAMESPACE_URL,customer+':'+message_id)); request_id=None
    monkeypatch.setattr(routes,'REQUEST_TIMEOUT_SECONDS',0.1)
    async def check():
        nonlocal request_id
        await db.open_pool()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.post('/api/chat',json={'message':'离线请求时间预算','client_message_id':message_id})
                assert response.status_code==504 and response.json()['code']=='REQUEST_TIMEOUT' and response.json()['retryable']
                request_id=response.json()['request_id']
                trace=await client.get('/api/traces/'+request_id)
                assert trace.status_code==200 and trace.json()[-1]['error']=='REQUEST_TIMEOUT'
        finally:
            async with db.get_connection() as connection:
                await connection.execute('DELETE FROM sessions WHERE session_id=%s AND customer_id=%s',(session_id,customer))
                if request_id: await connection.execute('DELETE FROM traces WHERE request_id=%s',(request_id,))
            await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)


def test_demo_status_is_read_only_sanitized_and_owned(monkeypatch):
    """O5快照不能调用模型、泄露原始参数或越权恢复会话。"""
    import asyncio, httpx
    from app import db
    from app.main import app
    from app.adapters.model import ChatModelAdapter
    async def forbidden(*args,**kwargs):raise AssertionError('管理页不可调用模型')
    monkeypatch.setattr(ChatModelAdapter,'complete_with_tools',forbidden)
    async def check():
        await db.open_pool()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                result=await client.get('/api/demo/status')
                assert result.status_code==200
                data=result.json()
                assert data['database']['status']=='available' and not data['executions']
                assert data['document_count']==len(data['sources']) and data['chunk_count']==sum(s['chunk_count'] for s in data['sources'])
                assert (await client.get('/api/demo/status?session_id=not-owned-session')).status_code==404
                assert not any(key in result.text for key in ['api_key','base_url','recent_messages','arguments_summary','reasoning_content'])
        finally:await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)
