/** 当前筛选、真实比较和最近查询的已有订单上下文。 */
import type { Comparison, SearchConstraints, Order } from '../types';
interface Props { constraints: SearchConstraints; comparison: Comparison | null; order: Order | null }
export function ContextPanel({ constraints, comparison, order }: Props) {
  return <div className="context-panel"><section className="context-card"><h2>▤ 当前筛选</h2><dl className="detail-facts"><dt>预算</dt><dd>{constraints.budget_max_fen === null ? '不限' : `≤ ¥${(constraints.budget_max_fen / 100).toFixed(2)}`}</dd><dt>用途</dt><dd>{constraints.use_case || '全部'}</dd><dt>库存</dt><dd>{constraints.in_stock_only ? '仅有货' : '包含无货'}</dd></dl></section><section className="context-card"><h2>⚖ 商品对比</h2><ComparisonPanel comparison={comparison} /></section><section className="context-card"><h2>▤ 最近查询的已有订单</h2>{order ? <><p>{order.order_id}</p><strong>实付 ¥{(order.paid_total_fen / 100).toFixed(2)}</strong><p>{order.logistics.summary}</p><span className="badge">合成演示订单</span></> : <p>请在“我的订单”中查看订单详情</p>}</section><section className="context-card"><h2>◇ 退换货说明</h2><p>政策咨询可在聊天中提问；模拟申请请在售后页准备并显式确认。</p></section></div>;
}
export function ComparisonPanel({ comparison }: { comparison: Comparison | null }) {
  if (!comparison) return <p>选择两款商品，再点击“对比所选两款”</p>;
  function display(field: string, value: string | number | boolean | null) {
    if (value === null) return '未知';
    if (field === 'sale_price_fen') return `¥${(Number(value) / 100).toFixed(2)}`;
    if (typeof value === 'boolean') return value ? '主动降噪' : '无主动降噪';
    return String(value);
  }
  return <><div className="comparison-scroll"><table><thead><tr><th>字段</th>{comparison.product_ids.map(id => <th key={id}>{id}</th>)}</tr></thead><tbody>{comparison.rows.map(row => <tr key={row.field}><th>{row.field === 'sale_price_fen' ? '到手价' : row.label}</th>{row.values.map((value,index) => <td key={index}>{display(row.field,value)}</td>)}</tr>)}</tbody></table></div><p className="muted">{comparison.recommendation_basis.join(' ')}</p></>;
}
