/** 筛选控件驱动真实商品接口，不生成助手回复。 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { fetchProducts, fetchProduct, fetchComparison } from '../api';
import type { Product, SearchConstraints, Comparison } from '../types';
import { AfterSalesWorkspace } from '../components/AfterSalesWorkspace';
import { ProductCard } from '../components/ProductCard';
import { DetailDrawer } from '../components/DetailDrawer';
import { ComparisonPanel } from '../components/ContextPanel';
import { MessageComposer, Conversation } from '../components/Conversation';
import type { useShoppingSession } from '../hooks/useShoppingSession';

export const defaultConstraints: SearchConstraints = { query: '', budget_max_fen: 30000, use_case: '通勤', in_stock_only: true };
interface Props { comparison: Comparison | null; onComparisonChange: (value: Comparison | null) => void; onConstraintsChange: (value: SearchConstraints) => void; chat:ReturnType<typeof useShoppingSession>; chatAvailable:boolean; chatUnavailableReason:string }
export function ShoppingPage({ comparison, onComparisonChange, onConstraintsChange, chat, chatAvailable, chatUnavailableReason }: Props) {
  const [source,setSource] = useState('手动筛选');
  const [query, setQuery] = useState(''), [budget, setBudget] = useState('300'), [useCase, setUseCase] = useState('通勤');
  const [stockOnly, setStockOnly] = useState(true), [applied, setApplied] = useState(defaultConstraints);
  const [products, setProducts] = useState<Product[]>([]), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [selected, setSelected] = useState<string[]>([]), [comparing, setComparing] = useState(false), [compareError, setCompareError] = useState('');
  const [detailId, setDetailId] = useState<string | null>(null), [detail, setDetail] = useState<Product | null>(null);
  const [detailLoading, setDetailLoading] = useState(false), [detailError, setDetailError] = useState('');
  const searchVersion = useRef(0), compareVersion = useRef(0), detailVersion = useRef(0);
  const hadChatView = useRef(false);
  /** 清除旧候选，过期响应不能覆盖最新筛选。 */
  const loadProducts = useCallback(async (filters: SearchConstraints) => {
    setSource('手动筛选');
    const version = ++searchVersion.current; ++compareVersion.current;
    setLoading(true); setError(''); setProducts([]); setSelected([]); setCompareError(''); setComparing(false); onComparisonChange(null); setApplied(filters); onConstraintsChange(filters);
    try { const result = await fetchProducts({ ...filters, limit: 6 }); if (version === searchVersion.current) setProducts(result); }
    catch (reason) { if (version === searchVersion.current) setError(reason instanceof Error ? reason.message : '商品查询失败'); }
    finally { if (version === searchVersion.current) setLoading(false); }
  }, [onComparisonChange, onConstraintsChange]);
  useEffect(() => { void loadProducts(defaultConstraints); return () => { ++searchVersion.current; ++compareVersion.current; ++detailVersion.current; }; }, [loadProducts]);
  useEffect(() => {
    const view=chat.viewState;
    if (!view) { if (hadChatView.current) { hadChatView.current=false; ++detailVersion.current; setDetailId(null); setQuery(''); setBudget('300'); setUseCase('通勤'); setStockOnly(true); void loadProducts(defaultConstraints); } return; }
    hadChatView.current=true;
    ++searchVersion.current; ++compareVersion.current; ++detailVersion.current;
    setProducts(view.products); setSource('聊天候选'); setLoading(false); setError(''); setSelected([]); setCompareError(''); setComparing(false);
    setApplied(view.constraints); setQuery(view.constraints.query); setBudget(view.constraints.budget_max_fen===null?'':String(view.constraints.budget_max_fen/100)); setUseCase(view.constraints.use_case || ''); setStockOnly(view.constraints.in_stock_only);
    onConstraintsChange(view.constraints); onComparisonChange(view.comparison);
    setDetailId(view.focused_product?.product_id || null); setDetail(view.focused_product); setDetailLoading(false); setDetailError('');
  },[chat.viewState,onComparisonChange,onConstraintsChange,loadProducts]);
  function applyFilters(event: FormEvent) {
    event.preventDefault();
    const fen = budget.trim() === '' ? null : Math.round(Number(budget) * 100);
    if (fen !== null && (!Number.isSafeInteger(fen) || fen < 0)) { setError('预算请输入有效的非负金额'); return; }
    void loadProducts({ query: query.trim(), budget_max_fen: fen, use_case: useCase || null, in_stock_only: stockOnly });
  }
  function selectProduct(id: string) {
    ++compareVersion.current; setComparing(false); setCompareError(''); onComparisonChange(null);
    setSelected(current => current.includes(id) ? current.filter(item => item !== id) : current.length < 2 ? [...current, id] : current);
  }
  async function compareSelected() {
    if (selected.length !== 2) return;
    const version = ++compareVersion.current; setComparing(true); setCompareError('');
    try { const result = await fetchComparison([selected[0], selected[1]]); if (version === compareVersion.current) onComparisonChange(result); }
    catch (reason) { if (version === compareVersion.current) setCompareError(reason instanceof Error ? reason.message : '比较失败'); }
    finally { if (version === compareVersion.current) setComparing(false); }
  }
  async function openProduct(id: string) {
    const version = ++detailVersion.current; setDetailId(id); setDetail(null); setDetailLoading(true); setDetailError('');
    try { const result = await fetchProduct(id); if (version === detailVersion.current) setDetail(result); }
    catch (reason) { if (version === detailVersion.current) setDetailError(reason instanceof Error ? reason.message : '商品详情失败'); }
    finally { if (version === detailVersion.current) setDetailLoading(false); }
  }
  const closeDetail = useCallback(() => { ++detailVersion.current; setDetailId(null); }, []);
  return <div className="shopping-page catalog-page"><div className="session-toolbar"><span>{chat.sessionId?'已保存会话':'新会话 · 首条消息后保存'}</span><button disabled={chat.busy} onClick={chat.startNewSession}>新建会话</button><select aria-label="恢复会话" value={chat.sessionId || ''} disabled={chat.busy} onChange={event=>event.target.value && void chat.restoreSession(event.target.value)}><option value="">选择最近会话</option>{chat.sessionId && !chat.sessions.some(item=>item.session_id===chat.sessionId) && <option value={chat.sessionId}>{chat.sessionTitle || "当前历史会话"}</option>}{chat.sessions.map(session=><option key={session.session_id} value={session.session_id}>{session.title}</option>)}</select></div>{chat.restoreError && <div className="error-panel" role="alert"><p>会话恢复失败：{chat.restoreError}</p><button disabled={chat.busy} onClick={()=>chat.restoreTarget && void chat.restoreSession(chat.restoreTarget)}>重试恢复会话</button></div>}<Conversation messages={chat.messages} busy={chat.busy}/><MessageComposer draft={chat.draft} onDraftChange={chat.setDraft} onSubmit={()=>void chat.submitMessage()} busy={chat.busy} available={chatAvailable} unavailableReason={chatUnavailableReason} error={chat.error}/><AfterSalesWorkspace chat={chat}/>{!chat.error && Boolean(chat.viewState?.citations.length) && <section className="context-card policy-sources"><h2>政策来源 · 项目演示资料</h2>{chat.viewState?.citations.map(hit=><details key={hit.chunk_id}><summary>{hit.title} · {hit.document_id} · {hit.chunk_id}</summary><p className="policy-excerpt">{hit.excerpt}</p></details>)}</section>}<p className="catalog-intro">{chat.error?'本次操作未完成；卡片为此前成功保存的状态。':''}{source}结果 · 手动浏览不改变聊天候选；聊天指代以最新聊天搜索为准。</p>
    <form className="filter-form" onSubmit={applyFilters}>
      <label>名称或编号<input value={query} onChange={event => setQuery(event.target.value)} placeholder="例如 A1、静听" /></label>
      <label>预算上限（元）<input type="number" min="0" step="0.01" value={budget} onChange={event => setBudget(event.target.value)} placeholder="不限" /></label>
      <label>用途<select value={useCase} onChange={event => setUseCase(event.target.value)}><option value="">全部用途</option>{['通勤','运动','居家','旅行','游戏'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label className="stock-filter"><input type="checkbox" checked={stockOnly} onChange={event => setStockOnly(event.target.checked)} />仅有货</label><button className="primary" type="submit" disabled={loading}>{loading ? '查询中…' : '筛选商品'}</button>
    </form>
    <div className="result-toolbar"><p>每次最多展示 6 款 · 当前选择 {selected.length}/2</p><button onClick={() => void compareSelected()} disabled={selected.length !== 2 || comparing || loading}>{comparing ? '比较中…' : '对比所选两款'}</button></div>
    <div aria-live="polite">{loading && <p>正在加载商品…</p>}{error && <div className="error-panel" role="alert"><p>{error}</p><button onClick={() => void loadProducts(applied)}>重试商品查询</button></div>}{!loading && !error && products.length === 0 && <div className="empty-panel"><h2>没有符合条件的商品</h2><p>请修改预算、用途或仅有货条件。</p></div>}</div>
    <div className="products-grid">{products.map(product => <ProductCard key={product.product_id} product={product} selected={selected.includes(product.product_id)} selectionDisabled={selected.length === 2} onSelect={() => selectProduct(product.product_id)} onDetail={() => void openProduct(product.product_id)} />)}</div>
    {compareError && <div className="error-panel" role="alert"><p>{compareError}</p><button onClick={() => void compareSelected()}>重试比较</button></div>}
    {comparison && <section className="inline-comparison context-card"><h2>商品对比</h2><ComparisonPanel comparison={comparison} /></section>}
    <DetailDrawer open={detailId !== null} title="商品详情" onClose={closeDetail}>{detailLoading ? <p>正在加载商品详情…</p> : detailError ? <div className="error-panel" role="alert"><p>{detailError}</p><button onClick={() => detailId && void openProduct(detailId)}>重试商品详情</button></div> : detail && <><ProductCard product={detail} /><dl className="detail-facts"><dt>商品编号</dt><dd>{detail.product_id}</dd><dt>原价</dt><dd>¥{(detail.list_price_fen / 100).toFixed(2)}</dd><dt>优惠金额</dt><dd>¥{(detail.discount_fen / 100).toFixed(2)}</dd><dt>优惠条件</dt><dd>{detail.promotion_eligible ? '本商品适用原价满200元减20元' : '本商品不适用满减'}</dd></dl></>}</DetailDrawer>
  </div>;
}
