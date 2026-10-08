"""O4 必要验证；真实数据库状态与局部故障夹具，绝不替代在线RAG。"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from contextlib import asynccontextmanager
import pytest
from psycopg.types.json import Jsonb
from app import db
from app.agent.state import save_session, load_session
from app.agent.tools import LocalToolExecutor, build_tool_definitions
from app.config import get_settings
from app.schemas import SessionState, DomainError
from app.services import after_sales, knowledge


def test_after_sales_transactional_lifecycle_and_task_restore():
    async def check():
        await db.open_pool()
        customer = get_settings().demo_customer_id
        id = 'o4-test-' + str(uuid4())
        session = SessionState(session_id=id,updated_at=datetime.now(timezone.utc))
        try:
            await db.init_schema()
            await save_session(session,customer)
            executor=LocalToolExecutor()
            generic=await executor.execute('prepare_after_sales',{'order_id':'DEMO20261003002','reason':'签收后退货'},session)
            assert generic.error.code=='NEEDS_INPUT' and session.view_state.after_sales_preview is None
            assert 'confirm_after_sales' not in {t['function']['name'] for t in build_tool_definitions()}
            missing=await executor.execute('prepare_after_sales',{'order_id':'DEMO20261003002'},session)
            assert missing.error.code=='NEEDS_INPUT' and session.pending_question=='after_sales_reason'
            await save_session(session,customer)
            session=await load_session(id,customer)
            assert session.after_sales_draft['order_id']=='DEMO20261003002'
            result=await executor.execute('prepare_after_sales',{'reason':'佩戴不合适'},session)
            assert result.ok
            p=session.view_state.after_sales_preview
            assert p.eligible and p.refund_amount_fen==27900 and p.application_id is None and p.status=='pending'
            assert p.policy_sources and p.policy_sources[0].document_id=='demo-policy-return'
            assert timedelta(minutes=9)<p.expires_at-datetime.now(timezone.utc)<=timedelta(minutes=10)
            await save_session(session,customer)
            again=await after_sales.prepare_after_sales(p.order_id,p.reason,id,customer)
            assert again.preview_id==p.preview_id
            assert (await executor.execute('search_products',{'budget_max_fen':20000,'use_case':'通勤'},session)).ok
            assert (await executor.execute('get_after_sales',{},session)).data['preview_id']==p.preview_id
            assert session.constraints.budget_max_fen==20000 and session.constraints.use_case=='通勤'
            await save_session(session,customer)
            assert (await load_session(id,customer)).view_state.after_sales_preview.preview_id==p.preview_id
            for action in [after_sales.confirm_after_sales,after_sales.cancel_after_sales]:
                with pytest.raises(DomainError):await action(p.preview_id,'different-session',customer)
                with pytest.raises(DomainError):await action(p.preview_id,id,'other-user')
            with pytest.raises(DomainError):await after_sales.get_after_sales(p.preview_id,'other-user')
            confirmed=await asyncio.gather(*[after_sales.confirm_after_sales(p.preview_id,id,customer) for _ in range(4)])
            assert len({v.application_id for v in confirmed})==1 and all(v.status=='submitted' for v in confirmed)
            assert (await after_sales.confirm_after_sales(p.preview_id,id,customer)).application_id==confirmed[0].application_id
            async with db.get_connection() as connection:
                cursor=await connection.execute('SELECT count(*) FROM after_sales WHERE preview_id=%s AND application_id IS NOT NULL',(p.preview_id,))
                assert (await cursor.fetchone())[0]==1
            with pytest.raises(DomainError) as conflict: await after_sales.cancel_after_sales(p.preview_id,id,customer)
            assert conflict.value.code=='STATE_CONFLICT'
            for order_id in ['DEMO20261003001','DEMO20261003003']:
                with pytest.raises(DomainError,match='运输中|超过'):
                    await after_sales.prepare_after_sales(order_id,'佩戴不合适',id,customer)
            cancelled=await after_sales.prepare_after_sales(p.order_id,'另一条申请原因',id,customer)
            assert (await after_sales.cancel_after_sales(cancelled.preview_id,id,customer)).status=='cancelled'
            assert (await after_sales.cancel_after_sales(cancelled.preview_id,id,customer)).status=='cancelled'
            with pytest.raises(DomainError) as conflict: await after_sales.confirm_after_sales(cancelled.preview_id,id,customer)
            assert conflict.value.code=='STATE_CONFLICT'
            old=await after_sales.prepare_after_sales(p.order_id,'旧预览原因',id,customer)
            new=await after_sales.prepare_after_sales(p.order_id,'更换原因预览',id,customer)
            assert old.preview_id!=new.preview_id and (await after_sales.get_after_sales(old.preview_id,customer)).status=='cancelled'
            expired=new.model_copy(update={'expires_at':datetime.now(timezone.utc)-timedelta(seconds=1)})
            async with db.get_connection() as connection:
                await connection.execute('UPDATE after_sales SET payload=%s WHERE preview_id=%s',(Jsonb(expired.model_dump(mode='json')),new.preview_id))
            with pytest.raises(DomainError) as expiry:await after_sales.confirm_after_sales(new.preview_id,id,customer)
            assert expiry.value.code=='PREVIEW_EXPIRED' and (await after_sales.get_after_sales(new.preview_id,customer)).status=='expired'
            assert any(v.application_id==confirmed[0].application_id for v in await after_sales.list_after_sales(customer))
            current=await after_sales.prepare_after_sales(p.order_id,'待更换订单原因',id,customer)
            session=await load_session(id,customer)
            changed=await executor.execute('prepare_after_sales',{'order_id':'DEMO20261003001'},session)
            assert changed.error.code=='NEEDS_INPUT' and session.after_sales_draft=={'order_id':'DEMO20261003001'}
            assert (await after_sales.get_after_sales(current.preview_id,customer)).status=='cancelled'
            assert (await executor.execute('get_after_sales',{},session)).error.code=='NEEDS_INPUT'
            await save_session(session,customer)
            assert (await load_session(id,customer)).after_sales_draft=={'order_id':'DEMO20261003001'}
            with pytest.raises(DomainError) as conflict:await after_sales.confirm_after_sales(current.preview_id,id,customer)
            assert conflict.value.code=='STATE_CONFLICT'
        finally:
            async with db.get_connection() as connection:
                await connection.execute('DELETE FROM after_sales WHERE session_id=%s',(id,))
                await connection.execute('DELETE FROM sessions WHERE session_id=%s',(id,))
            await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)


def test_after_sales_rechecks_snapshot_policy_and_order_conditions(monkeypatch):
    async def check():
        await db.open_pool()
        original=db.get_connection
        customer=get_settings().demo_customer_id
        try:
            async with original() as connection:
                async with connection.transaction(force_rollback=True):
                    @asynccontextmanager
                    async def same_connection():yield connection
                    monkeypatch.setattr(db,'get_connection',same_connection)
                    id='o4-rollback-'+str(uuid4())
                    await save_session(SessionState(session_id=id,updated_at=datetime.now(timezone.utc)),customer)
                    await connection.execute("UPDATE products SET payload=jsonb_set(payload,'{list_price_fen}','99900'::jsonb) WHERE product_id='DEMO-B2'")
                    p=await after_sales.prepare_after_sales('DEMO20261003002','佩戴不合适',id,customer)
                    assert p.refund_amount_fen==27900
                    await connection.execute("UPDATE orders SET payload=jsonb_set(payload,'{paid_total_fen}','12300'::jsonb) WHERE order_id='DEMO20261003002'")
                    with pytest.raises(DomainError) as conflict:await after_sales.confirm_after_sales(p.preview_id,id,customer)
                    assert conflict.value.code=='STATE_CONFLICT'
                    await connection.execute("UPDATE products SET payload=jsonb_set(payload,'{policy_id}','\"demo-no-return\"'::jsonb) WHERE product_id='DEMO-B2'")
                    with pytest.raises(DomainError) as denied:await after_sales.prepare_after_sales(p.order_id,'申请原因',id,customer)
                    assert denied.value.code=='INELIGIBLE'
        finally:await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)


def test_knowledge_whitelist_and_failure_remove_stale_citations(monkeypatch):
    from app.schemas import KnowledgeHit
    from app.services.policies import POLICY_DIR
    async def fail(*args,**kwargs):raise DomainError('EMBEDDING_FAILED','故障夹具：不生成向量',503)
    monkeypatch.setattr(knowledge,'_embed',fail)
    async def check():
        with pytest.raises(DomainError) as invalid:await knowledge.ingest_documents([POLICY_DIR/'README.md'])
        assert invalid.value.code=='INVALID_ARGUMENT'
        session=SessionState(session_id='offline-failure',updated_at=datetime.now(timezone.utc))
        session.view_state.citations=[KnowledgeHit(chunk_id='fixture-old',document_id='fixture-old',title='旧夹具',excerpt='不能冒充新引用',score=1)]
        result=await LocalToolExecutor().execute('search_knowledge',{'query':'退货条件'},session)
        assert not result.ok and result.error.code=='EMBEDDING_FAILED' and not session.view_state.citations and not result.view_updates.citations
        assert (await LocalToolExecutor().execute('confirm_after_sales',{},session)).error.code=='UNKNOWN_TOOL'
    asyncio.run(check())


def test_public_policy_and_structured_window_boundary():
    from app.services.policies import POLICIES,policy_reference
    from app.services.orders import get_order
    async def check():
        await db.open_pool()
        try:
            order=await get_order('DEMO20261003002',get_settings().demo_customer_id)
            days=POLICIES[order.policy_id]['return_days']
            assert f'{days}×24 小时' in policy_reference('demo-policy-return').excerpt
            assert after_sales.evaluate_eligibility(order,'佩戴不合适',order.signed_at+timedelta(days=days)).eligible
            assert not after_sales.evaluate_eligibility(order,'佩戴不合适',order.signed_at+timedelta(days=days,microseconds=1)).eligible
            assert not after_sales.evaluate_eligibility(order,'佩戴不合适',order.signed_at-timedelta(seconds=1)).eligible
        finally:await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)
