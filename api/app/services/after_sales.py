"""确定性整单模拟售后；事务锁定预览，确认不对模型开放。"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from psycopg.types.json import Jsonb
from app import db
from app.config import get_settings
from app.schemas import Order, Eligibility, AfterSalesPreview, DomainError
from app.services.policies import POLICIES, policy_reference


def is_complete_reason(reason: str) -> bool:
    """流程名称不等于申请原因；具体原因由用户提供。"""
    return len(reason.strip()) >= 2 and reason.strip() not in {'退货', '签收后退货', '申请退货', '申请售后', '售后', '签收后退货售后', '退款'}


def evaluate_eligibility(order: Order, reason: str, now: datetime) -> Eligibility:
    """期限使用签收时刻起7×24小时；金额不在模型中计算。"""
    policy = POLICIES.get(order.policy_id)
    sources = policy['source_ids'] if policy else []
    explanation = '符合演示退货规则；尚未提交，请在十分钟内通过界面按钮确认'
    eligible = False
    if order.customer_id != get_settings().demo_customer_id:
        explanation = '订单不属于当前演示用户'
    elif not is_complete_reason(reason):
        explanation = '请填写具体申请原因（至少两个字符）'
    elif order.status != 'delivered' or order.signed_at is None:
        explanation = '运输中或未签收订单不支持本首版的签收后退货流程'
    elif not policy or not policy['return_allowed']:
        explanation = '商品政策未知或不允许本演示退货，无法批准预览'
    elif order.signed_at > now or now - order.signed_at > timedelta(days=policy['return_days']):
        explanation = '签收时间异常或已超过演示政策的七天期限'
    else:
        eligible = True
    return Eligibility(eligible=eligible, explanation=explanation, policy_source_ids=sources)

async def _order(connection, order_id: str, customer_id: str) -> Order:
    cursor = await connection.execute('SELECT payload FROM orders WHERE order_id=%s AND customer_id=%s FOR SHARE', (order_id, customer_id))
    row = await cursor.fetchone()
    if not row:
        raise DomainError('ORDER_NOT_FOUND', '未找到当前用户的订单')
    return Order.model_validate({k:v for k,v in row[0].items() if not k.startswith('_')})

async def _eligibility(connection, order: Order, reason: str, now: datetime) -> Eligibility:
    result = evaluate_eligibility(order, reason, now)
    if result.eligible:
        for item in order.items:
            cursor = await connection.execute('SELECT payload FROM products WHERE product_id=%s FOR SHARE', (item.product_id,))
            row = await cursor.fetchone()
            item_policy = POLICIES.get(row[0].get('policy_id')) if row else None
            if not item_policy or not item_policy['return_allowed'] or row[0].get('policy_id') != order.policy_id:
                return Eligibility(eligible=False, explanation='订单商品政策未知、不一致或不允许演示退货', policy_source_ids=result.policy_source_ids)
    return result

async def _session(connection, session_id: str, customer_id: str):
    cursor = await connection.execute('SELECT state FROM sessions WHERE session_id=%s AND customer_id=%s FOR UPDATE', (session_id, customer_id))
    row = await cursor.fetchone()
    if not row:
        raise DomainError('SESSION_NOT_FOUND', '未找到当前用户的会话')
    return row[0]

async def _write(connection, preview: AfterSalesPreview):
    await connection.execute('UPDATE after_sales SET status=%s,application_id=%s,payload=%s WHERE preview_id=%s', (preview.status, preview.application_id, Jsonb(preview.model_dump(mode='json')), preview.preview_id))

async def _attach(connection, session_id: str, customer_id: str, preview: AfterSalesPreview):
    # 只更新售后字段，保留导购条件、候选及原生历史。
    await connection.execute("UPDATE sessions SET state=jsonb_set(jsonb_set(jsonb_set(state,'{pending_after_sales_id}',%s::jsonb),'{view_state,after_sales_preview}',%s::jsonb),'{after_sales_draft}',%s::jsonb),updated_at=now() WHERE session_id=%s AND customer_id=%s", (Jsonb(preview.preview_id), Jsonb(preview.model_dump(mode='json')), Jsonb({'order_id':preview.order_id,'reason':preview.reason}), session_id, customer_id))

async def _expire(connection, preview: AfterSalesPreview) -> AfterSalesPreview:
    if preview.status == 'pending' and datetime.now(timezone.utc) >= preview.expires_at:
        preview.status = 'expired'
        preview.explanation = '预览已过期，未提交；请重新准备预览'
        await _write(connection, preview)
    return preview

async def invalidate_changed_previews(order_id: str | None, reason: str | None, session_id: str, customer_id: str):
    """明确更换订单/原因时取消旧待确认预览，失败的新输入也不能提交旧内容。"""
    async with db.get_connection() as connection:
        async with connection.transaction():
            session = await _session(connection,session_id,customer_id)
            cursor = await connection.execute("SELECT payload FROM after_sales WHERE session_id=%s AND customer_id=%s AND status='pending' FOR UPDATE",(session_id,customer_id))
            for row in await cursor.fetchall():
                old = await _expire(connection,AfterSalesPreview.model_validate(row[0]))
                changed = (order_id is not None and old.order_id != order_id) or (reason is not None and old.reason != reason.strip())
                if changed and old.status == 'pending':
                    old.status = 'cancelled'
                    old.explanation = '申请订单或原因已更换，旧预览已取消；未提交'
                    await _write(connection,old)
                if session.get('pending_after_sales_id') == old.preview_id:
                    await _attach(connection,session_id,customer_id,old)

async def prepare_after_sales(order_id: str, reason: str, session_id: str, customer_id: str) -> AfterSalesPreview:
    """同一有效预览复用；更换订单/原因先作废旧待确认预览。"""
    reason = reason.strip()
    await invalidate_changed_previews(order_id,reason,session_id,customer_id)
    async with db.get_connection() as connection:
        async with connection.transaction():
            session = await _session(connection, session_id, customer_id)
            now = datetime.now(timezone.utc)
            order = await _order(connection, order_id, customer_id)
            eligibility = await _eligibility(connection, order, reason, now)
            if not eligibility.eligible:
                raise DomainError('INELIGIBLE', eligibility.explanation, 422)
            cursor = await connection.execute("SELECT payload FROM after_sales WHERE session_id=%s AND customer_id=%s AND status='pending' FOR UPDATE", (session_id,customer_id))
            for row in await cursor.fetchall():
                old = await _expire(connection, AfterSalesPreview.model_validate(row[0]))
                if old.status == 'pending' and old.order_id == order_id and old.reason == reason and old.refund_amount_fen == order.paid_total_fen:
                    await _attach(connection,session_id,customer_id,old)
                    return old
                if old.status == 'pending':
                    old.status = 'cancelled'
                    old.explanation = '申请订单或原因已更换，旧预览已取消；未提交'
                    await _write(connection,old)
            preview = AfterSalesPreview(preview_id=str(uuid4()),order_id=order_id,reason=reason,status='pending',eligible=True,explanation=eligibility.explanation,refund_amount_fen=order.paid_total_fen,policy_source_ids=eligibility.policy_source_ids,policy_sources=[policy_reference(id) for id in eligibility.policy_source_ids],expires_at=now+timedelta(minutes=10),application_id=None)
            await connection.execute('INSERT INTO after_sales(preview_id,customer_id,session_id,status,payload) VALUES (%s,%s,%s,%s,%s)', (preview.preview_id,customer_id,session_id,preview.status,Jsonb(preview.model_dump(mode='json'))))
            await _attach(connection,session_id,customer_id,preview)
            return preview

async def _transition(preview_id: str, session_id: str, customer_id: str, confirm: bool) -> AfterSalesPreview:
    error = None
    async with db.get_connection() as connection:
        async with connection.transaction():
            session = await _session(connection,session_id,customer_id)
            cursor = await connection.execute('SELECT payload FROM after_sales WHERE preview_id=%s AND session_id=%s AND customer_id=%s FOR UPDATE', (preview_id,session_id,customer_id))
            row = await cursor.fetchone()
            if not row:
                raise DomainError('AFTER_SALES_NOT_FOUND', '未找到当前会话/用户的售后记录')
            preview = await _expire(connection, AfterSalesPreview.model_validate(row[0]))
            if confirm and preview.status == 'submitted':
                return preview  # 已提交的幂等重放不生成新ID。
            if not confirm and preview.status == 'cancelled':
                return preview
            if preview.status == 'expired':
                error = DomainError('PREVIEW_EXPIRED','预览已过期，不能提交或取消；请重新预览',410)
            elif preview.status != 'pending':
                error = DomainError('STATE_CONFLICT','该预览已取消或提交，不能执行此操作；已提交申请不支持撤销',409)
            elif session.get('pending_after_sales_id') != preview_id:
                error = DomainError('STATE_CONFLICT','该预览不是会话当前预览，请恢复并检查后再操作',409)
            elif confirm:
                order = await _order(connection,preview.order_id,customer_id)
                eligibility = await _eligibility(connection,order,preview.reason,datetime.now(timezone.utc))
                if not eligibility.eligible or order.paid_total_fen != preview.refund_amount_fen or eligibility.policy_source_ids != preview.policy_source_ids:
                    error = DomainError('STATE_CONFLICT','订单条件或金额已变化，不能提交此预览，请重新预览',409)
                else:
                    preview.status = 'submitted'
                    preview.application_id = str(uuid4())
                    preview.explanation = '模拟售后申请已保存；不表示商家批准、退款执行或到账'
            else:
                preview.status = 'cancelled'
                preview.explanation = '待确认预览已取消，未提交申请'
            await _write(connection,preview)
            if session.get('pending_after_sales_id') == preview_id:
                await _attach(connection,session_id,customer_id,preview)
    if error:
        raise error  # 过期状态已提交数据库，不能因410而回滚。
    return preview

async def confirm_after_sales(preview_id: str, session_id: str, customer_id: str) -> AfterSalesPreview:
    return await _transition(preview_id,session_id,customer_id,True)

async def cancel_after_sales(preview_id: str, session_id: str, customer_id: str) -> AfterSalesPreview:
    return await _transition(preview_id,session_id,customer_id,False)

async def get_after_sales(preview_id: str, customer_id: str) -> AfterSalesPreview:
    async with db.get_connection() as connection:
        async with connection.transaction():
            cursor = await connection.execute('SELECT payload FROM after_sales WHERE preview_id=%s AND customer_id=%s FOR UPDATE', (preview_id,customer_id))
            row = await cursor.fetchone()
            if not row:
                raise DomainError('AFTER_SALES_NOT_FOUND','未找到当前用户的售后记录')
            return await _expire(connection,AfterSalesPreview.model_validate(row[0]))

async def list_after_sales(customer_id: str) -> list[AfterSalesPreview]:
    async with db.get_connection() as connection:
        cursor = await connection.execute('SELECT preview_id FROM after_sales WHERE customer_id=%s ORDER BY (payload->>\'expires_at\') DESC LIMIT 50',(customer_id,))
        ids = [row[0] for row in await cursor.fetchall()]
    return [await get_after_sales(id,customer_id) for id in ids]
