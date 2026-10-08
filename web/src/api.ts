/** 集中 HTTP 客户端，错误保持后端契约，不将 501 当成功。 */
import type { ApiError, HealthResponse, ChatRequest, ChatResponse, SessionSummary, SessionResponse, Product, SearchProductsArgs, Comparison, Order, PreviewAfterSalesRequest, SessionActionRequest, AfterSalesPreview, KnowledgeSource, TraceEvent, EvalReport, CapabilityStatus } from './types';

export class ApiRequestError extends Error {
  constructor(public readonly status: number, public readonly error: ApiError) { super(error.message); }
}
async function request<T>(path: string, body?: unknown, method=body === undefined ? 'GET' : 'POST'): Promise<T> {
  const response = await fetch(`/api${path}`, { method, headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  let result: unknown;
  try { result = await response.json(); } catch { throw new Error(response.status>=500?'后端暂不可用，请显式重试':'服务响应无效，请稍后重试'); }
  if (!response.ok) {
    const error = result as Partial<ApiError>;
    throw new ApiRequestError(response.status, { code: error.code ?? 'HTTP_ERROR', message: error.message ?? '本次请求失败，请重试', retryable: error.retryable ?? false, request_id: error.request_id ?? '' });
  }
  return result as T;
}
/** 获取真实健康状态，包括数据库降级。 */
export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch('/api/health');
  if (!response.ok && response.status !== 503) throw new Error('健康检查失败');
  return await response.json() as HealthResponse;
}
/** 非流式真实会话；失败状态显式保留。 */
export const sendMessage = (body: ChatRequest) => request<ChatResponse>('/chat', body);
/** 会话列表与恢复。 */
export const fetchSessions = () => request<SessionSummary[]>('/sessions');
export const fetchSession = (id: string) => request<SessionResponse>(`/sessions/${encodeURIComponent(id)}`);
/** 管理分页与限定顾客的实际删除结果。 */
export const fetchSessionPage = (offset=0,limit=20) => request<import('./types').SessionPage>(`/sessions/page?offset=${offset}&limit=${limit}`);
export const deleteSession = (id:string) => request<import('./types').SessionDeletionResult>(`/sessions/${encodeURIComponent(id)}`,undefined,'DELETE');
export const deleteSessions = (session_ids:string[]) => request<import('./types').SessionDeletionResult>('/sessions/delete',{session_ids});
export const deleteAllSessions = (expected_count:number) => request<import('./types').SessionDeletionResult>('/sessions',{expected_count},'DELETE');
/** 商品筛选、详情与两款比较。 */
export const fetchProducts = (filters: Partial<SearchProductsArgs> = {}) => {
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value !== undefined && value !== null) query.set(key, String(value)); });
  return request<Product[]>(`/products?${query}`);
};
export const fetchProduct = (id: string) => request<Product>(`/products/${encodeURIComponent(id)}`);
export const fetchComparison = (product_ids: [string, string]) => request<Comparison>('/products/compare', { product_ids });
/** 已有订单列表与订单物流。 */
export const fetchOrders = () => request<Order[]>('/orders');
export const fetchOrder = (id: string) => request<Order>(`/orders/${encodeURIComponent(id)}`);
/** 售后预览、显式确认、取消与列表。 */
export const previewAfterSales = (body: PreviewAfterSalesRequest) => request<AfterSalesPreview>('/after-sales/preview', body);
export const confirmAfterSales = (id: string, body: SessionActionRequest) => request<AfterSalesPreview>(`/after-sales/${encodeURIComponent(id)}/confirm`, body);
export const cancelAfterSales = (id: string, body: SessionActionRequest) => request<AfterSalesPreview>(`/after-sales/${encodeURIComponent(id)}/cancel`, body);
export const fetchAfterSales = () => request<AfterSalesPreview[]>('/after-sales');
/** 演示管理只读接口。 */
export const fetchKnowledgeSources = () => request<KnowledgeSource[]>('/knowledge/sources');
export const fetchTrace = (id: string) => request<TraceEvent[]>(`/traces/${encodeURIComponent(id)}`);
export const fetchEvalReport = () => request<EvalReport>('/evaluations/latest');
export const fetchCapabilities = () => request<CapabilityStatus[]>('/capabilities');
export const fetchDemoStatus = (id:string|null) => request<import('./types').DemoStatus>(`/demo/status${id?'?session_id='+encodeURIComponent(id):''}`);

export const createSession = () => request<SessionResponse>('/sessions', {});
export const fetchAfterSalesDetail = (id:string) => request<AfterSalesPreview>(`/after-sales/${encodeURIComponent(id)}`);
