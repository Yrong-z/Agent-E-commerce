"""真实数据库/ASGI 会话管理；只删除本次随机测试顾客，绝不清空演示用户。"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from uuid import uuid4
import httpx
import pytest
from psycopg.types.json import Jsonb
from app import db,routes
from app.agent import state
from app.config import get_settings
from app.main import app
from app.schemas import SessionState,ChatResponse,DomainError,AfterSalesPreview

def test_scope_pagination_deletion_and_business_preservation(monkeypatch):
    customer='session-test-'+str(uuid4());other='session-other-'+str(uuid4())
    settings=get_settings().model_copy(update={'demo_customer_id':customer})
    monkeypatch.setattr(routes,'get_settings',lambda:settings)
    ids=[str(uuid4()) for _ in range(25)];foreign=str(uuid4());request_ids=[str(uuid4()) for _ in range(3)]
    preview=str(uuid4());application=str(uuid4())
    async def check():
        await db.open_pool()
        try:
            for index,id in enumerate(ids):
                session=SessionState(session_id=id,title=f'session-test-{index}',updated_at=datetime.now(timezone.utc))
                if index==0:session.response_cache={'test':{'response':{'request_id':request_ids[0]}},'shared':{'response':{'request_id':request_ids[1]}}}
                await state.save_session(session,customer)
            other_session=SessionState(session_id=foreign,updated_at=datetime.now(timezone.utc),response_cache={'shared':{'response':{'request_id':request_ids[1]}}})
            await state.save_session(other_session,other)
            sale=AfterSalesPreview(preview_id=preview,order_id='isolated-order',reason='isolated-reason',status='submitted',eligible=True,explanation='测试记录，非实际申请',refund_amount_fen=19900,policy_source_ids=[],expires_at=datetime.now(timezone.utc),application_id=application)
            async with db.get_connection() as conn:
                await conn.execute('INSERT INTO after_sales(preview_id,customer_id,session_id,application_id,status,payload) VALUES (%s,%s,%s,%s,%s,%s)',(preview,customer,ids[0],application,'submitted',Jsonb(sale.model_dump(mode='json'))))
                for request_id in request_ids:await conn.execute('INSERT INTO traces(request_id,payload) VALUES (%s,%s)',(request_id,Jsonb({'test':True})))
                before=[]
                for table in ('products','orders','knowledge_chunks'):
                    row=await (await conn.execute(f'SELECT count(*),md5(string_agg(row_to_json(t)::text,\'\' ORDER BY row_to_json(t)::text)) FROM {table} t')).fetchone();before.append(row)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                first=(await client.get('/api/sessions/page')).json();older=(await client.get('/api/sessions/page?offset=20')).json()
                assert first['total']==25 and len(first['items'])==20 and first['has_more']
                assert len(older['items'])==5 and not older['has_more'] and ids[0] in {s['session_id'] for s in older['items']}
                assert len((await client.get('/api/sessions')).json())==20
                for body in ({'session_ids':[]},{'session_ids':['']},{'session_ids':['x']*101},{'session_ids':[ids[0]],'customer_id':other}):
                    assert (await client.post('/api/sessions/delete',json=body)).status_code==422
                for body in ({},{'expected_count':-1},{'expected_count':True},{'expected_count':23,'customer_id':other}):
                    assert (await client.request('DELETE','/api/sessions',json=body)).status_code==422
                assert (await client.get('/api/sessions/page?limit=51')).status_code==422
                assert (await client.get('/api/sessions/page?offset=-1')).status_code==422
                one=(await client.delete('/api/sessions/'+ids[1])).json();assert one['deleted_count']==1
                repeat=(await client.delete('/api/sessions/'+ids[1])).json();assert repeat['deleted_count']==0 and repeat['not_found_ids']==[ids[1]]
                batch=(await client.post('/api/sessions/delete',json={'session_ids':[ids[2],ids[2],foreign,'missing']})).json()
                assert batch['deleted_ids']==[ids[2]] and batch['not_found_ids']==[foreign,'missing']
                mismatch=await client.request('DELETE','/api/sessions',json={'expected_count':25})
                assert mismatch.status_code==409 and mismatch.json()['code']=='SESSION_COUNT_CHANGED'
                result=(await client.request('DELETE','/api/sessions',json={'expected_count':23})).json()
                assert result['deleted_count']==23 and result['deleted_trace_count']==1 and ids[0] in result['deleted_ids']
                assert (await client.get('/api/sessions/'+ids[0])).status_code==404
                assert (await client.get('/api/sessions/page')).json()['total']==0
                assert (await client.request('DELETE','/api/sessions',json={'expected_count':0})).json()['deleted_count']==0
                assert (await client.get('/api/after-sales')).json()[0]['application_id']==application
            assert (await state.load_session(foreign,other)).session_id==foreign
            async with db.get_connection() as conn:
                retained=await (await conn.execute('SELECT request_id FROM traces WHERE request_id=ANY(%s)',(request_ids,))).fetchall()
                assert {row[0] for row in retained}==set(request_ids[1:])
                for index,table in enumerate(('products','orders','knowledge_chunks')):
                    assert await (await conn.execute(f'SELECT count(*),md5(string_agg(row_to_json(t)::text,\'\' ORDER BY row_to_json(t)::text)) FROM {table} t')).fetchone()==before[index]
        finally:
            async with db.get_connection() as conn:
                await conn.execute('DELETE FROM sessions WHERE customer_id=ANY(%s)',([customer,other],))
                await conn.execute('DELETE FROM after_sales WHERE preview_id=%s',(preview,))
                await conn.execute('DELETE FROM traces WHERE request_id=ANY(%s)',(request_ids,))
            await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)

def test_busy_session_rollback_and_no_resurrection(monkeypatch):
    customer='session-busy-'+str(uuid4());settings=get_settings().model_copy(update={'demo_customer_id':customer})
    monkeypatch.setattr(routes,'get_settings',lambda:settings)
    id=str(uuid4());idle=str(uuid4())
    async def check():
        await db.open_pool();entered=asyncio.Event();release=asyncio.Event()
        async def offline_turn(request,session,**kwargs):
            entered.set();await release.wait()
            return ChatResponse(request_id=str(uuid4()),session_id=session.session_id,answer='仅并发测试夹具，不是在线模型',status='completed',view_state=session.view_state)
        monkeypatch.setattr(routes,'run_agent_turn',offline_turn)
        try:
            saved=SessionState(session_id=id,updated_at=datetime.now(timezone.utc))
            await state.save_session(saved,customer);await state.save_session(SessionState(session_id=idle,updated_at=datetime.now(timezone.utc)),customer)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                task=asyncio.create_task(client.post('/api/chat',json={'session_id':id,'message':'busy regression','client_message_id':str(uuid4())}))
                await entered.wait()
                for method,path,body in [('DELETE','/api/sessions/'+id,None),('POST','/api/sessions/delete',{'session_ids':[idle,id]}),('DELETE','/api/sessions',{'expected_count':2})]:
                    result=await client.request(method,path,json=body)
                    assert result.status_code==409 and result.json()['code']=='SESSION_BUSY'
                assert (await client.get('/api/sessions/page')).json()['total']==2
                release.set();assert (await task).status_code==200
                original=state.get_connection
                class FailingConnection:
                    def __init__(self,conn):self.conn=conn
                    def transaction(self):return self.conn.transaction()
                    async def execute(self,sql,params=None):
                        if sql.startswith('DELETE FROM traces'):raise RuntimeError('transaction regression')
                        return await self.conn.execute(sql,params)
                @asynccontextmanager
                async def failure_connection():
                    async with original() as conn:yield FailingConnection(conn)
                with monkeypatch.context() as patch:
                    patch.setattr(state,'get_connection',failure_connection)
                    with pytest.raises(RuntimeError):await state.delete_customer_sessions(customer,[id,idle])
                assert (await client.get('/api/sessions/page')).json()['total']==2
                assert (await client.delete('/api/sessions/'+id)).json()['deleted_count']==1
                with pytest.raises(DomainError) as error:await state.save_session(saved,customer,allow_create=False)
                assert error.value.code=='SESSION_NOT_FOUND'
                assert (await client.get('/api/sessions/'+id)).status_code==404
        finally:
            release.set()
            async with db.get_connection() as conn:await conn.execute('DELETE FROM sessions WHERE customer_id=%s',(customer,))
            await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)
