"""O2 最少价格边界断言；售后测试仍待实现。"""
import pytest
from app.services.pricing import calculate_offer

@pytest.mark.parametrize('price,eligible,discount,sale', [
    (19900, False, 0, 19900), (19999, True, 0, 19999),
    (20000, True, 2000, 18000), (29900, True, 2000, 27900),
    (29900, False, 0, 29900),
])
def test_offer_boundaries(price, eligible, discount, sale):
    """低于/等于门槛与不适用商品，金额不依赖模型。"""
    offer = calculate_offer(price, eligible)
    assert (offer.discount_fen, offer.sale_price_fen) == (discount, sale)

@pytest.mark.parametrize('price', [-1, 19.99, True])
def test_price_requires_nonnegative_integer_fen(price):
    """拒绝负数、元浮点和布尔值冒充整数分。"""
    with pytest.raises(ValueError):
        calculate_offer(price, True)

def test_seed_preserves_same_id_owned_by_other_source(monkeypatch):
    """在回滚事务中验证同名外部记录不能被种子覆盖，不改持久数据。"""
    import asyncio
    from contextlib import asynccontextmanager
    from app import db
    from scripts.seed_demo import seed_demo_data
    original_connection = db.get_connection
    async def check():
        await db.open_pool()
        try:
            async with original_connection() as connection:
                async with connection.transaction(force_rollback=True):
                    await connection.execute("UPDATE products SET payload=jsonb_set(payload,'{_seed_source}','\"other-source\"'::jsonb) WHERE product_id='DEMO-A1'")
                    cursor = await connection.execute("SELECT payload FROM products WHERE product_id='DEMO-A1'")
                    before = (await cursor.fetchone())[0]
                    @asynccontextmanager
                    async def same_transaction():
                        yield connection
                    monkeypatch.setattr(db,'get_connection',same_transaction)
                    await seed_demo_data()
                    cursor = await connection.execute("SELECT payload FROM products WHERE product_id='DEMO-A1'")
                    assert (await cursor.fetchone())[0] == before
        finally:
            await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)

def test_order_amount_is_immutable_price_snapshot(monkeypatch):
    """事务内修改商品现价，订单仍读取原实付；退出自动回滚。"""
    import asyncio
    from contextlib import asynccontextmanager
    from app import db
    from app.config import get_settings
    from app.adapters import commerce
    from app.services.catalog import get_product
    from app.services.orders import get_order
    async def check():
        await db.open_pool()
        try:
            async with db.get_connection() as connection:
                async with connection.transaction(force_rollback=True):
                    await connection.execute("UPDATE products SET payload=jsonb_set(payload,'{list_price_fen}','49900'::jsonb) WHERE product_id='DEMO-B2'")
                    @asynccontextmanager
                    async def same_transaction():
                        yield connection
                    monkeypatch.setattr(commerce,'get_connection',same_transaction)
                    assert (await get_product('DEMO-B2')).sale_price_fen == 47900
                    order = await get_order('DEMO20261003002',get_settings().demo_customer_id)
                    assert order.paid_total_fen == order.items[0].paid_price_fen == 27900
        finally:
            await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)

# O3 状态与编排验证：离线模型夹具只验证局部逻辑，不代表在线模型通过。
def test_partial_constraints_distinguish_omission_and_clear():
    from app.schemas import SearchConstraints,SearchProductsArgs
    from app.agent.state import merge_search_constraints
    current=SearchConstraints(query='耳机',budget_max_fen=30000,use_case='通勤',in_stock_only=False)
    patch=SearchProductsArgs(budget_max_fen=20000)
    updated=merge_search_constraints(current,patch.model_dump(exclude_unset=True))
    assert updated.budget_max_fen==20000 and updated.use_case=='通勤' and updated.in_stock_only is False and updated.query=='耳机'
    cleared=merge_search_constraints(updated,{'budget_max_fen':None,'use_case':None,'query':''})
    assert cleared.budget_max_fen is None and cleared.use_case is None and not cleared.in_stock_only


def test_tools_candidates_empty_cleanup_and_pending_order():
    import asyncio
    from datetime import datetime,timezone
    from app import db
    from app.schemas import SessionState
    from app.agent.tools import LocalToolExecutor,build_tool_definitions
    async def check():
        await db.open_pool()
        try:
            session=SessionState(session_id='offline-state-check',updated_at=datetime.now(timezone.utc))
            executor=LocalToolExecutor()
            assert {tool['function']['name'] for tool in build_tool_definitions()}=={'search_products','get_product','compare_products','get_order','get_logistics','search_knowledge','prepare_after_sales','get_after_sales'}
            assert (await executor.execute('search_products',{'budget_max_fen':30000,'use_case':'通勤','in_stock_only':True,'limit':2},session)).ok
            assert session.candidate_product_ids==['DEMO-A1','DEMO-B2']
            assert (await executor.execute('get_product',{'reference':'第二款'},session)).data['product_id']=='DEMO-B2'
            assert session.candidate_product_ids==['DEMO-A1','DEMO-B2']
            assert (await executor.execute('compare_products',{},session)).ok
            missing=await executor.execute('get_logistics',{},session)
            assert missing.error.code=='NEEDS_INPUT' and session.pending_question=='logistics_order_id'
            assert session.active_task=='orders' and session.candidate_product_ids==['DEMO-A1','DEMO-B2']
            assert (await executor.execute('get_logistics',{'order_id':'DEMO20261003001'},session)).ok
            assert session.pending_question is None and session.view_state.order.order_id=='DEMO20261003001'
            assert (await executor.execute('search_products',{'budget_max_fen':20000},session)).ok
            assert session.constraints.use_case=='通勤' and session.constraints.in_stock_only and session.candidate_product_ids==['DEMO-A1']
            assert (await executor.execute('get_product',{'reference':'第二款'},session)).error.code=='REFERENCE_NOT_FOUND'
            assert (await executor.execute('search_products',{'budget_max_fen':1},session)).ok
            assert not session.candidate_product_ids and not session.view_state.products
            assert session.view_state.comparison is None and session.view_state.focused_product is None
            assert session.view_state.order.order_id=='DEMO20261003001'
            assert (await executor.execute('search_products',{'budget_max_fen':True},session)).error.code=='INVALID_ARGUMENT'
            assert (await executor.execute('confirm_after_sales',{},session)).error.code=='UNKNOWN_TOOL'
        finally: await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)


def _offline_completion(calls=None,content=None):
    """合法 SDK 数据夹具，永不作为在线证据。"""
    from openai.types.chat import ChatCompletion
    return ChatCompletion.model_validate({'id':'offline-fixture','object':'chat.completion','created':0,'model':'offline-fixture','choices':[{'index':0,'finish_reason':'tool_calls' if calls else 'stop','message':{'role':'assistant','content':content,'reasoning_content':'隐藏字段不应保存','tool_calls':calls}}]})


def _native_call(id,name,args):
    import json
    return {'id':id,'type':'function','function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False) if not isinstance(args,str) else args}}


def _enable_offline_fixture(monkeypatch):
    from app.config import get_settings
    from pydantic import SecretStr
    from app.agent import runtime
    settings=get_settings().model_copy(update={'chat_base_url':'http://offline.invalid','chat_model':'offline-fixture','chat_api_key':SecretStr('offline-fixture-key')})
    monkeypatch.setattr(runtime,'get_settings',lambda:settings)


def test_native_pairing_real_services_and_whole_turn_history(monkeypatch):
    import asyncio
    from datetime import datetime,timezone
    from app import db
    from app.agent import runtime
    from app.agent.state import append_history_turn
    from app.schemas import ChatRequest,SessionState
    _enable_offline_fixture(monkeypatch)
    observed=[]; traces=[]
    responses=[_offline_completion([_native_call('native-search','search_products',{'budget_max_fen':30000,'use_case':'通勤','limit':2})]),_offline_completion(content='离线夹具解释，不代表在线验收')]
    async def complete(self,messages,tools,tool_choice='auto'):
        observed.append(messages.copy())
        return responses.pop(0)
    async def trace(event): traces.append(event)
    monkeypatch.setattr(runtime.ChatModelAdapter,'complete_with_tools',complete)
    monkeypatch.setattr(runtime,'record_trace_event',trace)
    async def check():
        await db.open_pool()
        try:
            session=SessionState(session_id='offline-native-check',updated_at=datetime.now(timezone.utc))
            response=await runtime.run_agent_turn(ChatRequest(message='离线验证',client_message_id='test'),session)
            assert response.status=='completed' and [p.product_id for p in response.view_state.products]==['DEMO-A1','DEMO-B2']
            assert observed[1][-1]['role']=='tool' and observed[1][-1]['tool_call_id']=='native-search'
            assert '隐藏字段不应保存' not in str(session.recent_messages)
            assert any(event.tool_name=='search_products' and event.error is None for event in traces)
            for i in range(8): append_history_turn(session,[{'role':'user','content':str(i)},{'role':'assistant','content':'夹具'}])
            assert len([m for m in session.recent_messages if m['role']=='user'])==6
            assert session.recent_messages[0]['role']=='user'
        finally: await db.close_pool()
    asyncio.run(check(),loop_factory=db.create_event_loop)


@pytest.mark.parametrize('mode,code', [('unknown','UNKNOWN_TOOL'),('invalid_json','INVALID_ARGUMENT'),('tool_limit','TOOL_LIMIT'),('model_limit','MODEL_CALL_LIMIT'),('timeout','MODEL_TIMEOUT')])
def test_agent_failures_limits_keep_native_pairs(monkeypatch,mode,code):
    import asyncio
    from datetime import datetime,timezone
    from app.agent import runtime
    from app.schemas import ChatRequest,SessionState,ToolResult
    _enable_offline_fixture(monkeypatch)
    model_calls=[]; executed=[]; traces=[]
    async def complete(self,messages,tools,tool_choice='auto'):
        model_calls.append(1)
        if mode=='timeout': await asyncio.sleep(0.03)
        calls=[_native_call('c'+str(len(model_calls)), 'nonexistent' if mode=='unknown' else 'search_products','{' if mode=='invalid_json' else {})]
        if mode=='tool_limit': calls=[_native_call('c'+str(i),'search_products',{}) for i in range(9)]
        return _offline_completion(calls)
    original=runtime.LocalToolExecutor.execute
    async def execute(self,name,args,session):
        if mode in {'tool_limit','model_limit'}:
            executed.append(1)
            return ToolResult(ok=True,data=[],view_updates=session.view_state)
        return await original(self,name,args,session)
    async def trace(event): traces.append(event)
    monkeypatch.setattr(runtime.ChatModelAdapter,'complete_with_tools',complete)
    monkeypatch.setattr(runtime.LocalToolExecutor,'execute',execute)
    monkeypatch.setattr(runtime,'record_trace_event',trace)
    async def check():
        session=SessionState(session_id='offline-errors',updated_at=datetime.now(timezone.utc))
        response=await runtime.run_agent_turn(ChatRequest(message='离线错误边界',client_message_id='test'),session,timeout_seconds=0.01 if mode=='timeout' else 5)
        assert response.status=='failed' and response.error.code==code
        assert len(model_calls)<=4 and len(executed)<=8
        native_ids=[call['id'] for m in session.recent_messages for call in m.get('tool_calls',[])]
        result_ids=[m['tool_call_id'] for m in session.recent_messages if m['role']=='tool']
        assert native_ids==result_ids
        assert traces and not response.view_state.products
    asyncio.run(check())


def test_missing_chat_configuration_never_calls_model(monkeypatch):
    """缺配置只产生明确失败；不依赖 embedding，不外呼，不填假卡片。"""
    import asyncio
    from datetime import datetime,timezone
    from app.agent import runtime
    from app.config import get_settings
    from app.schemas import ChatRequest,SessionState
    from pydantic import SecretStr
    config=get_settings().model_copy(update={'chat_api_key':SecretStr('')})
    monkeypatch.setattr(runtime,'get_settings',lambda:config)
    traces=[]
    async def trace(event): traces.append(event)
    async def no_call(*args,**kwargs): raise AssertionError('缺配置不得调用模型')
    monkeypatch.setattr(runtime,'record_trace_event',trace)
    monkeypatch.setattr(runtime.ChatModelAdapter,'complete_with_tools',no_call)
    async def check():
        session=SessionState(session_id='offline-config',updated_at=datetime.now(timezone.utc))
        response=await runtime.run_agent_turn(ChatRequest(message='查商品',client_message_id='test'),session)
        assert response.status=='failed' and response.error.code=='MODEL_NOT_CONFIGURED' and not response.view_state.products
        assert any(event.error=='MODEL_NOT_CONFIGURED' for event in traces)
    asyncio.run(check())
