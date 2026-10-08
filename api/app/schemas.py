"""统一接口、领域和工具参数模型；金额单位为整数分。"""
from datetime import datetime
from typing import Any, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

class ContractModel(BaseModel):
    """拒绝未知字段，防止参数拼写漂移。"""
    model_config = ConfigDict(extra='forbid')

class ApiError(ContractModel):
    """统一错误响应。"""
    code: str
    message: str
    retryable: bool = False
    request_id: str

class DomainError(Exception):
    """确定性业务失败，由 HTTP 层转换为 ApiError。"""
    def __init__(self, code: str, message: str, status_code: int = 404):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

class ProductSpecs(ContractModel):
    """商品参数；未知值保留为空。"""
    wearing_style: str | None = None
    anc: bool | None = None
    battery_hours: float | None = Field(default=None, ge=0)

class Product(ContractModel):
    """商品事实及计算后的价格。"""
    product_id: str
    name: str
    image_url: str
    category: str
    use_cases: list[str]
    list_price_fen: int = Field(ge=0)
    sale_price_fen: int = Field(ge=0)
    discount_fen: int = Field(ge=0)
    promotion_label: str | None
    stock: int = Field(ge=0)
    specs: ProductSpecs
    promotion_eligible: bool = False
    policy_id: str | None = None

class SearchConstraints(ContractModel):
    """当前筛选条件。"""
    query: str = ''
    budget_max_fen: int | None = Field(default=None, ge=0)
    use_case: str | None = None
    in_stock_only: bool = True

class SearchProductsArgs(SearchConstraints):
    """商品搜索工具参数。"""
    limit: int = Field(default=6, ge=1, le=6)

class GetProductArgs(ContractModel):
    """商品 ID 或候选指代。"""
    product_id: str | None = None
    reference: str | None = None
    @model_validator(mode='after')
    def require_reference(self):
        if not self.product_id and not self.reference:
            raise ValueError('需要 product_id 或 reference')
        return self

class CompareProductsRequest(ContractModel):
    """比较请求必须提供两个不同商品。"""
    product_ids: list[str] = Field(min_length=2, max_length=2)
    @model_validator(mode='after')
    def distinct_products(self):
        if self.product_ids[0] == self.product_ids[1]:
            raise ValueError('必须比较两款不同商品')
        return self

class CompareProductsArgs(ContractModel):
    """工具可从会话候选中补齐两款，执行时校验。"""
    product_ids: list[str] | None = Field(default=None, min_length=2, max_length=2)

class ComparisonRow(ContractModel):
    """对比字段及与商品顺序一致的两个值。"""
    field: str
    label: str
    values: list[str | int | float | bool | None] = Field(min_length=2, max_length=2)

class Comparison(ContractModel):
    """固定字段两款对比。"""
    product_ids: list[str] = Field(min_length=2, max_length=2)
    rows: list[ComparisonRow]
    recommendation_basis: list[str]

class OrderItem(ContractModel):
    """已有订单商品快照。"""
    product_id: str
    name: str
    quantity: int = Field(ge=1)
    paid_price_fen: int = Field(ge=0)

class LogisticsEvent(ContractModel):
    """物流节点。"""
    time: AwareDatetime
    description: str

class Logistics(ContractModel):
    """订单物流信息。"""
    summary: str
    events: list[LogisticsEvent] = Field(default_factory=list)

class Order(ContractModel):
    """演示用户已有订单。"""
    order_id: str
    customer_id: str
    items: list[OrderItem]
    paid_total_fen: int = Field(ge=0)
    status: Literal['shipped', 'delivered']
    signed_at: AwareDatetime | None
    logistics: Logistics
    policy_id: str

class GetOrderArgs(ContractModel):
    """订单和物流工具参数；未提供时保存待补订单号。"""
    order_id: str | None = Field(default=None, min_length=1)

class KnowledgeHit(ContractModel):
    """真实检索资料片段。"""
    chunk_id: str
    document_id: str
    title: str
    excerpt: str
    score: float

class SearchKnowledgeArgs(ContractModel):
    """政策检索工具参数。"""
    query: str = Field(min_length=1)
    product_id: str | None = None
    top_k: int = Field(default=3, ge=1, le=3)

class PrepareAfterSalesArgs(ContractModel):
    """模型仅能准备预览，不能确认。"""
    order_id: str | None = Field(default=None, min_length=1, max_length=100)
    reason: str | None = Field(default=None, min_length=1, max_length=500)

class PreviewAfterSalesRequest(ContractModel):
    """HTTP 预览请求。"""
    session_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)

class SessionActionRequest(ContractModel):
    """界面显式确认或取消请求。"""
    session_id: str = Field(min_length=1)

class GetAfterSalesArgs(ContractModel):
    """可恢复会话当前售后预览。"""
    preview_id: str | None = None

class PolicyReference(ContractModel):
    """确定性规则所引用的本地公开政策，不冒充向量检索。"""
    document_id: str
    title: str
    excerpt: str

class AfterSalesPreview(ContractModel):
    """模拟售后预览与申请状态。"""
    preview_id: str
    order_id: str
    reason: str
    status: Literal['pending', 'submitted', 'cancelled', 'expired']
    eligible: bool
    explanation: str
    refund_amount_fen: int = Field(ge=0)
    policy_source_ids: list[str]
    policy_sources: list[PolicyReference] = Field(default_factory=list)
    expires_at: AwareDatetime
    application_id: str | None

class SessionState(ContractModel):
    """可恢复业务状态，不包含隐藏推理。"""
    session_id: str
    constraints: SearchConstraints = Field(default_factory=SearchConstraints)
    candidate_product_ids: list[str] = Field(default_factory=list)
    focused_product_ids: list[str] = Field(default_factory=list)
    active_task: Literal['shopping', 'orders', 'after_sales', 'knowledge'] = 'shopping'
    pending_question: str | None = None
    pending_after_sales_id: str | None = None
    after_sales_draft: dict[str, str] = Field(default_factory=dict)
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    display_messages: list[dict[str, str]] = Field(default_factory=list)
    response_cache: dict[str, dict[str, Any]] = Field(default_factory=dict)
    view_state: 'ViewState' = Field(default_factory=lambda: ViewState())
    title: str = '新会话'
    candidate_limit: int = Field(default=6, ge=1, le=6)
    last_order_id: str | None = None
    updated_at: AwareDatetime

class ViewState(ContractModel):
    """只能由真实工具结果构造的展示状态。"""
    active_task: Literal['shopping', 'orders', 'after_sales', 'knowledge'] = 'shopping'
    products: list[Product] = Field(default_factory=list)
    focused_product: Product | None = None
    comparison: Comparison | None = None
    order: Order | None = None
    after_sales_preview: AfterSalesPreview | None = None
    citations: list[KnowledgeHit] = Field(default_factory=list)
    constraints: SearchConstraints = Field(default_factory=SearchConstraints)

class ChatRequest(ContractModel):
    """单轮用户输入及幂等消息 ID。"""
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)
    client_message_id: str = Field(min_length=1, max_length=100)

class ChatResponse(ContractModel):
    """一轮会话响应。"""
    request_id: str
    session_id: str
    answer: str
    status: Literal['completed', 'needs_input', 'failed']
    view_state: ViewState
    error: ApiError | None = None

class SessionSummary(ContractModel):
    """最近会话摘要。"""
    session_id: str
    title: str
    updated_at: AwareDatetime

class SessionPage(ContractModel):
    """当前顾客分页摘要；total 包括未加载历史。"""
    items: list[SessionSummary]
    total: int
    offset: int
    limit: int
    has_more: bool

class DeleteSessionsRequest(ContractModel):
    """限定批量数量，空白 ID 拒绝；重复 ID 由服务去重。"""
    session_ids: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def validate_ids(self):
        if any(not item.strip() or len(item) > 100 for item in self.session_ids):
            raise ValueError('会话 ID 必须为1至100字符且不为空白')
        return self

class DeleteAllSessionsRequest(ContractModel):
    """确认时的实际数量；数量变化需重新确认。"""
    expected_count: int = Field(ge=0,strict=True)

class SessionDeletionResult(ContractModel):
    """仅报告实际删除及未找到 ID，不把重复删除算作成功数量。"""
    deleted_count: int
    deleted_ids: list[str]
    not_found_ids: list[str] = Field(default_factory=list)
    deleted_trace_count: int = 0

class SessionResponse(ContractModel):
    """会话恢复结果。"""
    state: SessionState
    view_state: ViewState

class CapabilityStatus(ContractModel):
    """实现与验证分别记录。"""
    name: str
    implementation_status: Literal['implemented', 'reserved', 'not_implemented']
    verification_status: Literal['passed', 'failed', 'not_run']
    verified_at: AwareDatetime | None
    detail: str

class HealthResponse(ContractModel):
    """无付费外呼的实时基础设施健康检查。"""
    status: Literal['ok', 'degraded']
    application: Literal['ok'] = 'ok'
    chat_model: Literal['configured', 'not_configured'] = 'not_configured'
    database: Literal['ok', 'unavailable']
    pgvector: Literal['ok', 'unavailable']
    detail: str

class ToolResult(ContractModel):
    """本地和未来远程执行器共享返回语义。"""
    ok: bool
    data: Any = None
    error: ApiError | None = None
    view_updates: ViewState | None = None

class Offer(ContractModel):
    """确定性优惠结果。"""
    list_price_fen: int = Field(ge=0)
    discount_fen: int = Field(ge=0)
    sale_price_fen: int = Field(ge=0)
    promotion_label: str | None

class Eligibility(ContractModel):
    """售后资格与实际政策来源。"""
    eligible: bool
    explanation: str
    policy_source_ids: list[str]

class KnowledgeSource(ContractModel):
    """已入库资料摘要。"""
    document_id: str
    title: str
    chunk_count: int = Field(ge=0)

class TraceEvent(ContractModel):
    """执行摘要，不记录模型隐藏推理。"""
    request_id: str
    tool_name: str
    arguments_summary: str
    result_summary: str
    duration_ms: float = Field(ge=0)
    error: str | None
    checked_at: AwareDatetime | None = None
    sources: list[KnowledgeHit] = Field(default_factory=list)

class ServiceStatus(ContractModel):
    """只读状态；未检查不能显示为可用。"""
    status: Literal['available', 'unavailable', 'not_checked']
    checked_at: AwareDatetime | None
    detail: str

class ExecutionStep(ContractModel):
    """管理页只展示工具结果摘要，不返回原始参数。"""
    tool_name: str
    duration_ms: float
    error: str | None
    checked_at: AwareDatetime | None
    sources: list[KnowledgeHit]

class ExecutionRecord(ContractModel):
    request_id: str
    status: Literal['completed', 'needs_input', 'failed']
    checked_at: AwareDatetime | None
    steps: list[ExecutionStep]

class DemoStatus(ContractModel):
    """最小演示管理快照；无收费模型请求。"""
    backend: ServiceStatus
    database: ServiceStatus
    embedding: ServiceStatus
    chat: ServiceStatus
    chat_model: str
    embedding_model: str
    embedding_dimension: int | None
    sources: list[KnowledgeSource]
    document_count: int
    chunk_count: int
    corpus_models: list[dict[str, str | int | None]]
    executions: list[ExecutionRecord]

class EvalReport(ContractModel):
    """真实评测报告；未执行使用 not_run。"""
    checked_at: AwareDatetime | None
    git_commit: str | None
    environment: dict[str, str]
    case_count: int
    passed: int
    failed: int
    not_run: int
    cases: list[dict[str, Any]]

class ReviewSummary(ContractModel):
    """评价摘要仅预留，不注册为工具。"""
    product_id: str
    sample_count: int = Field(ge=0)
    strengths: list[str]
    weaknesses: list[str]
    source_ids: list[str]
    data_mode: str
