/** 前后端领域契约；字段保留 snake_case，金额统一为分。 */
export interface ApiError { code: string; message: string; retryable: boolean; request_id: string }
export interface ProductSpecs { wearing_style: string | null; anc: boolean | null; battery_hours: number | null }
export interface Product { product_id: string; name: string; image_url: string; category: string; use_cases: string[]; list_price_fen: number; sale_price_fen: number; discount_fen: number; promotion_label: string | null; stock: number; specs: ProductSpecs; promotion_eligible: boolean; policy_id: string | null }
export interface SearchConstraints { query: string; budget_max_fen: number | null; use_case: string | null; in_stock_only: boolean }
export interface SearchProductsArgs extends Partial<SearchConstraints> { limit?: number }
export interface GetProductArgs { product_id?: string | null; reference?: string | null }
export interface CompareProductsRequest { product_ids: [string, string] }
export interface CompareProductsArgs { product_ids?: [string, string] | null }
export interface GetOrderArgs { order_id?: string | null }
export interface SearchKnowledgeArgs { query: string; product_id?: string | null; top_k?: number }
export interface PrepareAfterSalesArgs { order_id?: string | null; reason?: string | null }
export interface GetAfterSalesArgs { preview_id?: string | null }
export interface ComparisonRow { field: string; label: string; values: [string | number | boolean | null, string | number | boolean | null] }
export interface Comparison { product_ids: [string, string]; rows: ComparisonRow[]; recommendation_basis: string[] }
export interface OrderItem { product_id: string; name: string; quantity: number; paid_price_fen: number }
export interface LogisticsEvent { time: string; description: string }
export interface Logistics { summary: string; events: LogisticsEvent[] }
export interface Order { order_id: string; customer_id: string; items: OrderItem[]; paid_total_fen: number; status: 'shipped' | 'delivered'; signed_at: string | null; logistics: Logistics; policy_id: string }
export interface KnowledgeHit { chunk_id: string; document_id: string; title: string; excerpt: string; score: number }
export interface PolicyReference { document_id:string; title:string; excerpt:string }
export interface AfterSalesPreview { preview_id: string; order_id: string; reason: string; status: 'pending' | 'submitted' | 'cancelled' | 'expired'; eligible: boolean; explanation: string; refund_amount_fen: number; policy_source_ids: string[]; policy_sources:PolicyReference[]; expires_at: string; application_id: string | null }
export interface SessionState { session_id: string; constraints: SearchConstraints; candidate_product_ids: string[]; focused_product_ids: string[]; active_task: 'shopping' | 'orders' | 'after_sales' | 'knowledge'; pending_question: string | null; pending_after_sales_id: string | null; after_sales_draft: Record<string,string>; recent_messages: Record<string, unknown>[]; display_messages: {role:string;content:string;status?:string}[]; response_cache: Record<string,unknown>; title:string; candidate_limit:number; last_order_id:string|null; view_state:ViewState; updated_at: string }
export interface ViewState { active_task: SessionState['active_task']; products: Product[]; focused_product: Product | null; comparison: Comparison | null; order: Order | null; after_sales_preview: AfterSalesPreview | null; citations: KnowledgeHit[]; constraints: SearchConstraints }
export interface ChatRequest { session_id?: string | null; message: string; client_message_id: string }
export interface ChatResponse { request_id: string; session_id: string; answer: string; status: 'completed' | 'needs_input' | 'failed'; view_state: ViewState; error:ApiError|null }
export interface SessionSummary { session_id: string; title: string; updated_at: string }
export interface SessionPage { items:SessionSummary[]; total:number; offset:number; limit:number; has_more:boolean }
export interface SessionDeletionResult { deleted_count:number; deleted_ids:string[]; not_found_ids:string[]; deleted_trace_count:number }
export interface SessionResponse { state: SessionState; view_state: ViewState }
export interface CapabilityStatus { name: string; implementation_status: 'implemented' | 'reserved' | 'not_implemented'; verification_status: 'passed' | 'failed' | 'not_run'; verified_at: string | null; detail: string }
export interface HealthResponse { status: 'ok' | 'degraded'; application: 'ok'; chat_model:'configured'|'not_configured'; database: 'ok' | 'unavailable'; pgvector: 'ok' | 'unavailable'; detail: string }
export interface ToolResult { ok: boolean; data: unknown; error: ApiError | null; view_updates: ViewState | null }
export interface Offer { list_price_fen: number; discount_fen: number; sale_price_fen: number; promotion_label: string | null }
export interface Eligibility { eligible: boolean; explanation: string; policy_source_ids: string[] }
export interface KnowledgeSource { document_id: string; title: string; chunk_count: number }
export interface TraceEvent { request_id: string; tool_name: string; arguments_summary: string; result_summary: string; duration_ms: number; error: string | null; checked_at:string|null; sources:KnowledgeHit[] }
export interface EvalReport { checked_at: string | null; git_commit: string | null; environment: Record<string, string>; case_count: number; passed: number; failed: number; not_run: number; cases: Record<string, unknown>[] }
export interface ReviewSummary { product_id: string; sample_count: number; strengths: string[]; weaknesses: string[]; source_ids: string[]; data_mode: string }
export interface PreviewAfterSalesRequest { session_id: string; order_id:string; reason:string }
export interface SessionActionRequest { session_id: string }
export type Page = 'shopping' | 'orders' | 'after-sales' | 'admin';
export interface ServiceStatus { status:'available'|'unavailable'|'not_checked'; checked_at:string|null; detail:string }
export interface ExecutionStep { tool_name:string; duration_ms:number; error:string|null; checked_at:string|null; sources:KnowledgeHit[] }
export interface ExecutionRecord { request_id:string; status:'completed'|'needs_input'|'failed'; checked_at:string|null; steps:ExecutionStep[] }
export interface DemoStatus { backend:ServiceStatus; database:ServiceStatus; embedding:ServiceStatus; chat:ServiceStatus; chat_model:string; embedding_model:string; embedding_dimension:number|null; sources:KnowledgeSource[]; document_count:number; chunk_count:number; corpus_models:{model:string|null;dimension:number|null}[]; executions:ExecutionRecord[] }
