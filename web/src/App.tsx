/** 应用外壳、四页切换和真实后端健康状态。 */
import { useCallback, useEffect, useState,useRef } from 'react';
import { fetchHealth } from './api';
import type { HealthResponse, Page, Comparison, Order,SessionSummary } from './types';
import { SessionManager } from './components/SessionManager';
import { Sidebar } from './components/Sidebar';
import { ContextPanel } from './components/ContextPanel';
import { ShoppingPage, defaultConstraints } from './pages/ShoppingPage';
import { OrdersPage } from './pages/OrdersPage';
import { AfterSalesPage } from './pages/AfterSalesPage';
import { DemoAdminPage } from './pages/DemoAdminPage';
import { useShoppingSession } from './hooks/useShoppingSession';

const titles: Record<Page, string> = { shopping: '选购助手', orders: '我的订单', 'after-sales': '售后服务', admin: '演示管理' };
export default function App() {
  const chat = useShoppingSession();
  const [page, setPage] = useState<Page>('shopping');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [healthCheckedAt,setHealthCheckedAt]=useState<string|null>(null);
  const [showContext, setShowContext] = useState(false);
  const [constraints, setConstraints] = useState(defaultConstraints);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [order, setOrder] = useState<Order | null>(null);
  const [manageSessions,setManageSessions]=useState(false),[singleDelete,setSingleDelete]=useState<SessionSummary|null>(null);
  const closeManager=useCallback(()=>{setManageSessions(false);setSingleDelete(null);},[]);
  const previousSession=useRef(chat.sessionId);
  useEffect(()=>{if(previousSession.current && !chat.sessionId){setPage('shopping');setShowContext(false);}previousSession.current=chat.sessionId;},[chat.sessionId]);
  /** 会话钩子驻留应用入口，页面切换保留真实会话。 */
  function navigateTo(next: Page) { setPage(next); }
  const refreshHealth = useCallback(async () => {
    setLoading(true); setError('');
    try { setHealth(await fetchHealth()); } catch { setHealth(null); setError('后端无法连接，请启动 API 后重试'); } finally { setHealthCheckedAt(new Date().toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai'}));setLoading(false); }
  }, []);
  useEffect(() => { void refreshHealth(); }, [refreshHealth]);
  useEffect(() => { if (chat.viewState) { setConstraints(chat.viewState.constraints); setComparison(chat.viewState.comparison); setOrder(chat.viewState.order); } else { setConstraints(defaultConstraints); setComparison(null); setOrder(null); } },[chat.viewState]);
  return <div className="app-shell">
    <Sidebar currentPage={page} onNavigate={navigateTo} sessions={chat.sessions} sessionId={chat.sessionId} busy={chat.busy} sessionsError={chat.sessionsError} onNewSession={()=>{chat.startNewSession();setPage('shopping');}} onRestore={id=>{setPage('shopping');void chat.restoreSession(id);}} onRefreshSessions={()=>void chat.refreshSessions()} onManage={()=>setManageSessions(true)} onDelete={setSingleDelete}/>
    <a className="skip-link" href="#main-content">跳到主要内容</a><main id="main-content" tabIndex={-1} className="main-panel">
      <header className="page-header"><div><h1>{titles[page]}</h1><p>选商品 · 看订单 · 办模拟售后</p></div><div className="header-actions"><span className="badge">合成演示数据</span><button className="context-toggle" onClick={() => setShowContext(!showContext)}>查看上下文</button></div></header>
      <section className={`health-strip ${health?.status === 'ok' ? 'ready' : ''}`} aria-live="polite" data-testid="health-status">
        <span className="status-dot" /><div>{loading ? '正在检查后端服务…' : error || (health?.status === 'ok' ? '基础服务已连接 · 可查询商品和订单' : health?.detail)}<small>检查时间：{healthCheckedAt??'未检查'}（北京时间） · {health?.chat_model==='configured'?'聊天服务已配置':health?'聊天模型未配置':'聊天状态待检查'} · 详细状态见演示管理</small></div><button onClick={() => void refreshHealth()} disabled={loading}>重新检查</button>
      </section>
      {chat.sessionNotice && <p className="session-notice" role="status">{chat.sessionNotice}</p>}
      <div className="page-content">{page === 'shopping' ? <ShoppingPage key={chat.sessionId || "new-session"} comparison={comparison} onComparisonChange={setComparison} onConstraintsChange={setConstraints} chat={chat} chatAvailable={health?.chat_model==='configured'} chatUnavailableReason={health?'聊天模型未配置，暂不可用；商品筛选和已有订单仍可使用。配置后重新检查服务。':'暂未连接后端，聊天状态未知；请重新检查服务。'} /> : page === 'orders' ? <OrdersPage onOrderViewed={setOrder} /> : page === 'after-sales' ? <AfterSalesPage chat={chat} /> : <DemoAdminPage sessionId={chat.sessionId} />}</div>
      <footer className="main-footer">本地合成数据演示 · 无真实商业系统接入</footer>
    </main>
    <aside className={`context-region ${showContext ? 'visible' : ''}`}><button className="context-close" onClick={() => setShowContext(false)}>关闭上下文</button><ContextPanel constraints={constraints} comparison={comparison} order={order} /></aside>
    <SessionManager open={manageSessions} single={singleDelete} onClose={closeManager} onRestore={id=>{setPage('shopping');void chat.restoreSession(id);}} chat={chat}/>
  </div>;
}
