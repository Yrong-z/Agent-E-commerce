/** 当前顾客已有合成订单、实付快照与物流详情。 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchOrders, fetchOrder } from '../api';
import type { Order } from '../types';
import { DetailDrawer } from '../components/DetailDrawer';
export function OrdersPage({ onOrderViewed }: { onOrderViewed: (order: Order) => void }) {
  const [orders, setOrders] = useState<Order[]>([]), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [lookup, setLookup] = useState(''), [detailId, setDetailId] = useState<string | null>(null), [detail, setDetail] = useState<Order | null>(null);
  const [detailLoading, setDetailLoading] = useState(false), [detailError, setDetailError] = useState('');
  const listVersion = useRef(0), detailVersion = useRef(0);
  const loadOrders = useCallback(async () => {
    const version = ++listVersion.current; setLoading(true); setError(''); setOrders([]);
    try { const result = await fetchOrders(); if (version === listVersion.current) setOrders(result); }
    catch (reason) { if (version === listVersion.current) setError(reason instanceof Error ? reason.message : '订单查询失败'); }
    finally { if (version === listVersion.current) setLoading(false); }
  }, []);
  useEffect(() => { void loadOrders(); return () => { ++listVersion.current; ++detailVersion.current; }; }, [loadOrders]);
  async function openOrder(id: string) {
    const version = ++detailVersion.current; setDetailId(id); setDetail(null); setDetailLoading(true); setDetailError('');
    try { const result = await fetchOrder(id); if (version === detailVersion.current) { setDetail(result); onOrderViewed(result); } }
    catch (reason) { if (version === detailVersion.current) setDetailError(reason instanceof Error ? reason.message : '订单详情失败'); }
    finally { if (version === detailVersion.current) setDetailLoading(false); }
  }
  const closeDetail = useCallback(() => { ++detailVersion.current; setDetailId(null); }, []);
  return <section className="orders-page"><p className="catalog-intro">以下是演示用户已有的合成订单，商品推荐不会创建订单。</p><form className="order-lookup" onSubmit={event => { event.preventDefault(); if (lookup.trim()) void openOrder(lookup.trim()); }}><label>已有订单号<input value={lookup} onChange={event => setLookup(event.target.value)} placeholder="DEMO20261003001" required /></label><button type="submit">查询订单</button></form>
    <div aria-live="polite">{loading && <p>正在加载已有订单…</p>}{error && <div role="alert" className="error-panel"><p>{error}</p><button onClick={() => void loadOrders()}>重试订单列表</button></div>}{!loading && !error && !orders.length && <p>当前演示用户暂无已有订单。</p>}</div>
    <div className="order-list">{orders.map(order => <article key={order.order_id} className="order-card"><div className="order-heading"><strong>{order.order_id}</strong><span className="badge">{order.status === 'shipped' ? '运输中' : '已签收'}</span></div>{order.items.map(item => <p key={item.product_id}>{item.name} × {item.quantity}</p>)}<strong className="order-price">实付 ¥{(order.paid_total_fen / 100).toFixed(2)}</strong><p>{order.logistics.summary}</p><button onClick={() => void openOrder(order.order_id)} aria-label={`查看订单${order.order_id}物流`}>查看订单与物流</button><small>合成演示订单 · 模拟售后请前往“售后服务”</small></article>)}</div>
    <DetailDrawer open={detailId !== null} title="已有订单与物流" onClose={closeDetail}>{detailLoading ? <p>正在加载订单与物流…</p> : detailError ? <div role="alert" className="error-panel"><p>{detailError}</p><button onClick={() => detailId && void openOrder(detailId)}>重试订单详情</button></div> : detail && <><span className="badge">已有合成演示订单</span><h3>{detail.order_id}</h3><p>{detail.status === 'shipped' ? '运输中' : '已签收'}</p>{detail.items.map(item => <p key={item.product_id}>{item.name} × {item.quantity} · 单价实付 ¥{(item.paid_price_fen / 100).toFixed(2)}</p>)}<p className="order-price">订单实付 ¥{(detail.paid_total_fen / 100).toFixed(2)}</p><p>签收时间：{detail.signed_at ? new Date(detail.signed_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'}) : '尚未签收'}</p><h3>物流节点</h3><p>{detail.logistics.summary}</p><ol>{detail.logistics.events.map((event,index) => <li key={index}><time>{new Date(event.time).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'})}</time><p>{event.description}</p></li>)}</ol><p className="muted">金额来自订单快照；模拟售后请前往“售后服务”。</p></>}</DetailDrawer>
  </section>;
}
