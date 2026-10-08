/** 真实预览，只有显式按钮可提交模拟申请。 */
import { useEffect, useState } from 'react';
import type { AfterSalesPreview as Preview } from '../types';
interface Props { preview: Preview; pending?: boolean; onConfirm: () => Promise<void>; onCancel: () => Promise<void> }
export function AfterSalesPreview({preview,pending=false,onConfirm,onCancel}:Props) {
  const [now,setNow]=useState(Date.now());
  useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[]);
  const expired=preview.status==='pending' && now>=Date.parse(preview.expires_at);
  const labels={pending:'待确认预览',submitted:'模拟申请已保存',cancelled:'已取消',expired:'预览已过期'};
  return <section className="context-card after-sales-card"><h2>{expired?'预览已过期':labels[preview.status]}</h2><dl className="detail-facts"><dt>订单</dt><dd>{preview.order_id}</dd><dt>申请原因</dt><dd>{preview.reason}</dd><dt>历史实付申请金额</dt><dd>¥{(preview.refund_amount_fen/100).toFixed(2)}</dd>{preview.status==='pending' && <><dt>有效期至</dt><dd>{new Date(preview.expires_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}（北京时间）</dd><dt>预览编号</dt><dd>{preview.preview_id}</dd></>}{preview.application_id && <><dt>申请编号</dt><dd>{preview.application_id}</dd></>}</dl><p>{expired?'十分钟预览已过期，未提交；请重新准备预览。':preview.explanation}</p><p className="muted">保存的是模拟申请，不表示商家批准、退款执行或到账。</p>{preview.policy_sources.map(source=><details key={source.document_id}><summary>{source.title} · {source.document_id}（确定性规则来源）</summary><p className="policy-excerpt">{source.excerpt}</p></details>)}{preview.status==='pending' && !expired && <div className="result-toolbar"><button disabled={pending || !preview.eligible} className="primary" onClick={()=>void onConfirm()}>{pending?'正在处理…':'确认模拟申请'}</button><button disabled={pending} onClick={()=>void onCancel()}>取消预览</button></div>}</section>;
}
