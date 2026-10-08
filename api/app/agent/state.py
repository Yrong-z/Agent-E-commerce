"""会话持久化、条件局部更新与最新候选指代；单进程串行执行。"""
import asyncio
from contextlib import asynccontextmanager, AsyncExitStack
from datetime import datetime, timezone
from weakref import WeakValueDictionary
from psycopg.types.json import Jsonb
from app.db import get_connection
from app.schemas import SessionState, SessionSummary, SearchConstraints, DomainError, SessionPage, SessionDeletionResult

_session_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_deleting_customers: set[str] = set()
_customer_operations: dict[str, int] = {}

@asynccontextmanager
async def session_lock(session_id: str, customer_id: str | None = None, *, wait: bool = True):
    """锁覆盖读取、模型执行和保存；不持有数据库长事务。"""
    if customer_id in _deleting_customers:
        raise DomainError('SESSION_BUSY','会话正在删除，请稍后重试',409)
    lock = _session_locks.setdefault(session_id, asyncio.Lock())
    if not wait and lock.locked():
        raise DomainError('SESSION_BUSY','所选会话正在处理，请等待结束后重试删除',409)
    if customer_id:
        _customer_operations[customer_id] = _customer_operations.get(customer_id,0) + 1
    try:
        async with lock:
            yield
    finally:
        if customer_id:
            _customer_operations[customer_id] -= 1
            if not _customer_operations[customer_id]:
                del _customer_operations[customer_id]

async def page_customer_sessions(customer_id: str, offset: int = 0, limit: int = 20) -> SessionPage:
    """同一数据库快照内读取总数与一页摘要，旧会话可继续翻页。"""
    async with get_connection() as connection:
        async with connection.transaction():
            await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cursor = await connection.execute('SELECT count(*) FROM sessions WHERE customer_id=%s',(customer_id,))
            total = (await cursor.fetchone())[0]
            cursor = await connection.execute('SELECT session_id,state,updated_at FROM sessions WHERE customer_id=%s ORDER BY updated_at DESC,session_id LIMIT %s OFFSET %s',(customer_id,limit,offset))
            items = [SessionSummary(session_id=row[0], title=row[1].get('title','会话'), updated_at=row[2]) for row in await cursor.fetchall()]
    return SessionPage(items=items,total=total,offset=offset,limit=limit,has_more=offset+len(items)<total)

async def delete_customer_sessions(customer_id: str, session_ids: list[str] | None = None, expected_count: int | None = None) -> SessionDeletionResult:
    """原子删除当前顾客会话；忙碌冲突；保留业务记录与无法可靠关联的旧trace。"""
    if customer_id in _deleting_customers or session_ids is None and _customer_operations.get(customer_id,0):
        raise DomainError('SESSION_BUSY','会话正在处理，请等待结束后重试删除',409)
    _deleting_customers.add(customer_id)  # 单进程内在首次 await 前封住新聊天/售后/创建入口。
    try:
        requested = list(dict.fromkeys(session_ids)) if session_ids is not None else None
        async with get_connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute('SELECT session_id FROM sessions WHERE customer_id=%s'+(' AND session_id=ANY(%s)' if requested is not None else ''),(customer_id,requested) if requested is not None else (customer_id,))
                owned = sorted(row[0] for row in await cursor.fetchall())
                if requested is None and len(owned) != expected_count:
                    raise DomainError('SESSION_COUNT_CHANGED','会话数量已变化，请刷新列表并重新确认删除全部',409)
                async with AsyncExitStack() as locks:
                    for session_id in owned:
                        await locks.enter_async_context(session_lock(session_id,wait=False))
                    cursor = await connection.execute('DELETE FROM sessions WHERE customer_id=%s AND session_id=ANY(%s) RETURNING session_id,state',(customer_id,owned))
                    rows = await cursor.fetchall()
                    deleted = sorted(row[0] for row in rows)
                    request_ids = {cached.get('response',{}).get('request_id') for _, payload in rows for cached in payload.get('response_cache',{}).values()}
                    request_ids.discard(None)
                    # 只有被删会话缓存里有确切请求ID，且不被任何保留会话引用的记录可删。
                    cursor = await connection.execute("DELETE FROM traces t WHERE request_id=ANY(%s) AND NOT EXISTS (SELECT 1 FROM sessions s, jsonb_each(COALESCE(s.state->'response_cache','{}'::jsonb)) c WHERE c.value->'response'->>'request_id'=t.request_id)",(list(request_ids),))
                    trace_count = cursor.rowcount
        return SessionDeletionResult(deleted_count=len(deleted),deleted_ids=deleted,not_found_ids=[item for item in requested or [] if item not in deleted],deleted_trace_count=trace_count)
    finally:
        _deleting_customers.discard(customer_id)

async def list_customer_sessions(customer_id: str) -> list[SessionSummary]:
    """仅列出当前顾客最近二十个实际保存的会话。"""
    async with get_connection() as connection:
        cursor = await connection.execute('SELECT session_id,state,updated_at FROM sessions WHERE customer_id=%s ORDER BY updated_at DESC,session_id LIMIT 20', (customer_id,))
        return [SessionSummary(session_id=row[0], title=row[1].get('title','会话'), updated_at=row[2]) for row in await cursor.fetchall()]

async def load_session(session_id: str, customer_id: str) -> SessionState:
    """未知或其他用户的会话不返回数据。"""
    async with get_connection() as connection:
        cursor = await connection.execute('SELECT state FROM sessions WHERE session_id=%s AND customer_id=%s', (session_id,customer_id))
        row = await cursor.fetchone()
    if row is None:
        raise DomainError('SESSION_NOT_FOUND','未找到该会话')
    session = SessionState.model_validate(row[0])
    session.view_state.active_task = session.active_task
    if session.pending_after_sales_id:
        from app.services.after_sales import get_after_sales
        session.view_state.after_sales_preview = await get_after_sales(session.pending_after_sales_id,customer_id)
    return session

async def save_session(session: SessionState, customer_id: str, *, allow_create: bool = True) -> None:
    """保存完整历史组和最多二十次请求缓存，不覆盖其他顾客。"""
    session.updated_at = datetime.now(timezone.utc)
    async with get_connection() as connection:
        if allow_create:
            cursor = await connection.execute('INSERT INTO sessions(session_id,customer_id,state,updated_at) VALUES (%s,%s,%s,%s) ON CONFLICT(session_id) DO UPDATE SET state=EXCLUDED.state,updated_at=EXCLUDED.updated_at WHERE sessions.customer_id=EXCLUDED.customer_id RETURNING session_id', (session.session_id,customer_id,Jsonb(session.model_dump(mode='json')),session.updated_at))
        else:
            cursor = await connection.execute('UPDATE sessions SET state=%s,updated_at=%s WHERE session_id=%s AND customer_id=%s RETURNING session_id',(Jsonb(session.model_dump(mode='json')),session.updated_at,session.session_id,customer_id))
        if await cursor.fetchone() is None:
            raise DomainError('SESSION_NOT_FOUND','未找到该会话')

def resolve_product_reference(reference: str, session: SessionState) -> str:
    """只解析当前候选顺序，不从详情焦点或历史回答提取 ID。"""
    indexes = {'第一款':0,'第一个':0,'第一件':0,'第二款':1,'第二个':1,'第二件':1,'第三款':2,'第三个':2}
    index = indexes.get(reference.strip())
    if index is None or index >= len(session.candidate_product_ids):
        raise DomainError('REFERENCE_NOT_FOUND','当前候选中没有该指代，请重新筛选或提供商品编号',422)
    return session.candidate_product_ids[index]

def merge_search_constraints(current: SearchConstraints, updates: SearchConstraints | dict) -> SearchConstraints:
    """仅合并实际提供字段；null 清除预算/用途，未提供保留原值。"""
    patch = updates.model_dump(exclude_unset=True) if isinstance(updates,SearchConstraints) else updates
    return SearchConstraints.model_validate({**current.model_dump(),**patch})

def append_history_turn(session: SessionState, turn: list[dict]) -> None:
    """按用户消息边界保留最后六轮；整组删掉，避免截断 tool 配对。"""
    messages = history_before_turn(session, turn[0]['content']) + turn
    starts = [i for i,message in enumerate(messages) if message['role']=='user']
    session.recent_messages = messages[starts[-6]:] if len(starts)>6 else messages

def history_before_turn(session: SessionState, message: str) -> list[dict]:
    """重试替换上一失败轮的完整原生片段，既有业务事实仍由会话保存。"""
    previous = session.display_messages
    retry = len(previous) >= 2 and previous[-1].get('status') == 'failed' and previous[-2].get('role') == 'user' and previous[-2]['content'] == message
    starts = [index for index, item in enumerate(session.recent_messages) if item['role'] == 'user']
    return session.recent_messages[:starts[-1]] if retry and starts else session.recent_messages

def append_display_turn(session: SessionState, message: str, answer: str, status: str) -> None:
    """明确失败后的相同输入重试只更新该轮结果，不再次追加用户消息。"""
    previous = session.display_messages
    retry = len(previous) >= 2 and previous[-1].get('status') == 'failed' and previous[-2].get('role') == 'user' and previous[-2]['content'] == message
    prefix = previous[:-1] if retry else previous + [{'role':'user','content':message}]
    session.display_messages = (prefix + [{'role':'assistant','content':answer,'status':status}])[-24:]
