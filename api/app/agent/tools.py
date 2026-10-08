"""八个可执行工具的唯一注册表：声明、校验与执行都从这里生成。"""
from typing import Any, Protocol
from uuid import uuid4
from pydantic import BaseModel, ValidationError
from app.schemas import SearchKnowledgeArgs, PrepareAfterSalesArgs, GetAfterSalesArgs, SearchProductsArgs, GetProductArgs, CompareProductsArgs, GetOrderArgs, SessionState, ToolResult, ApiError, DomainError
from app.config import get_settings
from app.services import catalog, orders, knowledge, after_sales
from app.agent.state import merge_search_constraints, resolve_product_reference

async def _search(args: SearchProductsArgs, session: SessionState):
    """局部合并条件，使用同一 O2 筛选，成功后清除旧候选与对比。"""
    patch = args.model_dump(exclude_unset=True)
    limit = patch.pop('limit',session.candidate_limit)
    constraints = merge_search_constraints(session.constraints,patch)
    products = await catalog.search_products(**constraints.model_dump(),limit=limit)
    session.constraints = constraints
    session.candidate_limit = limit
    session.candidate_product_ids = [p.product_id for p in products]
    session.focused_product_ids = []
    session.active_task = 'shopping'
    session.pending_question = None
    session.view_state.products = products
    session.view_state.constraints = constraints
    session.view_state.comparison = None
    session.view_state.focused_product = None
    return [p.model_dump(mode='json') for p in products]

async def _product(args: GetProductArgs, session: SessionState):
    """详情焦点独立于候选顺序。"""
    product_id = resolve_product_reference(args.reference,session) if args.reference else args.product_id
    if args.reference and args.product_id and product_id != args.product_id:
        raise DomainError('INVALID_ARGUMENT','商品编号与候选指代不一致',422)
    product = await catalog.get_product(product_id)
    session.focused_product_ids = [product.product_id]
    session.view_state.focused_product = product
    session.active_task = 'shopping'
    session.pending_question = None
    return product.model_dump(mode='json')

async def _compare(args: CompareProductsArgs, session: SessionState):
    """默认前两款，数量与存在性由 O2 服务校验。"""
    ids = args.product_ids or session.candidate_product_ids[:2]
    if len(ids)!=2:
        session.active_task = 'shopping'
        session.pending_question = 'product_ids'
        raise DomainError('NEEDS_INPUT','请先筛选两款商品或提供两款商品编号',422)
    comparison = await catalog.compare_products(ids)
    session.view_state.comparison = comparison
    session.view_state.focused_product = None
    session.focused_product_ids = []
    session.active_task = 'shopping'
    session.pending_question = None
    return comparison.model_dump(mode='json')

async def _order(args: GetOrderArgs, session: SessionState, logistics: bool = False):
    """顾客身份由服务端注入；缺订单号保存待补任务，不猜订单。"""
    session.active_task = 'orders'
    session.view_state.focused_product = None
    session.focused_product_ids = []
    if not args.order_id:
        session.pending_question = 'logistics_order_id' if logistics else 'order_id'
        raise DomainError('NEEDS_INPUT','请提供要查询的已有订单号',422)
    order = await orders.get_order(args.order_id,get_settings().demo_customer_id)
    data = await orders.get_logistics(args.order_id,get_settings().demo_customer_id) if logistics else order
    session.view_state.order = order
    session.last_order_id = order.order_id
    session.pending_question = None
    return data.model_dump(mode='json')

async def _logistics(args: GetOrderArgs, session: SessionState):
    """调用已有物流服务，保留导购条件。"""
    return await _order(args,session,True)

async def _knowledge(args: SearchKnowledgeArgs, session: SessionState):
    """每次检索先清引用，失败不展示旧证据。"""
    session.active_task = 'knowledge'
    session.view_state.citations = []
    session.pending_question = None
    hits = await knowledge.search_knowledge(**args.model_dump())
    session.view_state.citations = hits
    return {'hits':[hit.model_dump(mode='json') for hit in hits], 'evidence_status':'retrieved' if hits else 'insufficient', 'instruction':'仅按本次片段解释；未覆盖的条件、运费和承诺均无法确认；分数不是可信概率'}

async def _prepare(args: PrepareAfterSalesArgs, session: SessionState):
    """补充信息保存独立草稿；只准备预览，不能确认。"""
    session.active_task = 'after_sales'
    patch = {k:v.strip() for k,v in args.model_dump(exclude_unset=True).items() if v is not None}
    old = session.view_state.after_sales_preview
    if old and old.status == 'pending' and any(key in patch and patch[key] != getattr(old,key) for key in ('order_id','reason')):
        session.view_state.after_sales_preview = await after_sales.cancel_after_sales(old.preview_id,session.session_id,get_settings().demo_customer_id)
    if patch.get('order_id') and patch['order_id'] != session.after_sales_draft.get('order_id'):
        session.after_sales_draft = {}
    session.after_sales_draft.update(patch)
    draft = session.after_sales_draft
    if not draft.get('order_id') or not after_sales.is_complete_reason(draft.get('reason', '')):
        session.pending_question = 'after_sales_order_id' if not draft.get('order_id') else 'after_sales_reason'
        raise DomainError('NEEDS_INPUT','请补充售后订单号和具体申请原因；未创建申请',422)
    old = session.view_state.after_sales_preview
    if old and (old.order_id != draft['order_id'] or old.reason != draft['reason']):
        session.view_state.after_sales_preview = None
    preview = await after_sales.prepare_after_sales(draft['order_id'],draft['reason'],session.session_id,get_settings().demo_customer_id)
    session.pending_after_sales_id = preview.preview_id
    session.pending_question = None
    session.view_state.after_sales_preview = preview
    return preview.model_dump(mode='json')

async def _after_sales(args: GetAfterSalesArgs, session: SessionState):
    session.active_task = 'after_sales'
    if not args.preview_id and session.pending_question in ('after_sales_order_id','after_sales_reason'):
        raise DomainError('NEEDS_INPUT','售后草稿尚缺订单号或原因，请补充后继续；旧预览不能提交',422)
    id = args.preview_id or session.pending_after_sales_id
    if not id:
        session.pending_question = 'after_sales_reason' if session.after_sales_draft.get('order_id') else 'after_sales_order_id'
        raise DomainError('NEEDS_INPUT','当前没有售后预览，请补充订单号或申请原因；已有草稿字段已保留',422)
    preview = await after_sales.get_after_sales(id,get_settings().demo_customer_id)
    # 工具不能把其他会话的预览绑定成当前可提交预览。
    if id != session.pending_after_sales_id:
        return preview.model_dump(mode='json')
    session.view_state.after_sales_preview = preview
    session.pending_question = None
    return preview.model_dump(mode='json')

TOOL_REGISTRY = {
    'search_knowledge':(SearchKnowledgeArgs,'检索项目演示政策并返回真实片段；咨询政策不得创建售后申请。',_knowledge),
    'prepare_after_sales':(PrepareAfterSalesArgs,'准备模拟售后预览，缺订单号或原因时省略对应参数并追问；不能确认。',_prepare),
    'get_after_sales':(GetAfterSalesArgs,'恢复当前预览/申请，继续售后或聊天中确认时调用，只显示界面入口，不提交。',_after_sales),
    'search_products':(SearchProductsArgs,'搜索耳机；只传用户明确更新的条件，省略字段保留当前值，null 清除预算/用途。',_search),
    'get_product':(GetProductArgs,'查询商品详情；第一款/第二款用 reference，不改变候选顺序。',_product),
    'compare_products':(CompareProductsArgs,'比较两款商品；省略 IDs 使用最新候选前两款。',_compare),
    'get_order':(GetOrderArgs,'查询已有订单；缺订单号省略 order_id，返回待补信息。',_order),
    'get_logistics':(GetOrderArgs,'查询已有订单物流；缺订单号省略 order_id，追问后继续。',_logistics),
}
# 兼容现有契约命名，不维护另一份注册表。
TOOL_ARGUMENT_MODELS: dict[str,type[BaseModel]] = {name:item[0] for name,item in TOOL_REGISTRY.items()}

class ToolExecutor(Protocol):
    """未来远程执行边界，本轮只使用本地实现。"""
    async def execute(self, tool_name: str, arguments: dict[str,Any], session: SessionState) -> ToolResult: ...

def build_tool_definitions() -> list[dict[str,Any]]:
    """从注册表生成原生 JSON Schema；去掉默认值以免覆盖多轮条件。"""
    def without_defaults(value):
        if isinstance(value,dict):
            return {key:without_defaults(item) for key,item in value.items() if key!='default'}
        if isinstance(value,list):
            return [without_defaults(item) for item in value]
        return value
    return [{'type':'function','function':{'name':name,'description':description,'parameters':without_defaults(model.model_json_schema())}} for name,(model,description,_) in TOOL_REGISTRY.items()]

class LocalToolExecutor:
    """参数校验和业务分派，未知工具不执行，不声明预留能力。"""
    async def execute(self, tool_name: str, arguments: dict[str,Any], session: SessionState) -> ToolResult:
        entry = TOOL_REGISTRY.get(tool_name)
        code,message = 'UNKNOWN_TOOL','未知或尚未实现的工具'
        if entry:
            try:
                args = entry[0].model_validate(arguments, strict=True)
                data = await entry[2](args,session)
                return ToolResult(ok=True,data=data,view_updates=session.view_state.model_copy(deep=True))
            except ValidationError:
                code,message = 'INVALID_ARGUMENT','工具参数不符合契约'
            except DomainError as error:
                code,message = error.code,error.message
            except Exception:
                code,message = 'TOOL_FAILED','业务工具执行失败，请重试'
        return ToolResult(ok=False,error=ApiError(code=code,message=message,retryable=code=='TOOL_FAILED',request_id=str(uuid4())),view_updates=session.view_state.model_copy(deep=True))
