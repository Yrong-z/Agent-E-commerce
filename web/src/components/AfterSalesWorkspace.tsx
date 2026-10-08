/** 显式售后操作；所有状态来自专用接口，可恢复和重试。 */
import { useEffect, useRef, useState } from 'react';
import { previewAfterSales,confirmAfterSales,cancelAfterSales,fetchAfterSales } from '../api';
import type { AfterSalesPreview as Preview } from '../types';
import type { useShoppingSession } from '../hooks/useShoppingSession';
import { AfterSalesPreview } from './AfterSalesPreview';

export function AfterSalesWorkspace({chat,form=false}:{chat:ReturnType<typeof useShoppingSession>;form?:boolean}) {
  const [order,setOrder]=useState(''),[reason,setReason]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[records,setRecords]=useState<Preview[]>([]);
  const [recordsError,setRecordsError]=useState(''),[recordsLoading,setRecordsLoading]=useState(form);
  const working=useRef(false);
  const preview=chat.viewState?.after_sales_preview;
  async function loadRecords(){setRecordsLoading(true);setRecords([]);try{setRecords(await fetchAfterSales());setRecordsError('');}catch(e){setRecordsError(e instanceof Error?e.message:'记录加载失败');}finally{setRecordsLoading(false);}}
  useEffect(()=>{if(form) void loadRecords();},[form,chat.sessionId,preview?.status]);
  async function operate(action:'preview'|'confirm'|'cancel') {
    if(working.current || chat.busy)return;
    working.current=true;setBusy(true);setError('');
    try {
      await chat.performAfterSalesAction(async id=>{
        if(action==='preview') return await previewAfterSales({session_id:id,order_id:order.trim(),reason:reason.trim()});
        if(preview){if(action==='confirm') return await confirmAfterSales(preview.preview_id,{session_id:id});return await cancelAfterSales(preview.preview_id,{session_id:id});}
      });
      if(form)await loadRecords();
    } catch(e){setError(e instanceof Error?e.message:'操作失败，请显式重试');}
    finally{working.current=false;setBusy(false);}
  }
  if(!form && (chat.viewState?.active_task!=='after_sales' || chat.error || chat.busy)) return null;
  return <>{form && <section className="context-card"><h2>准备模拟售后预览</h2><p>输入已有订单号和具体原因。资格由演示政策判断，确认前只保存待确认预览，不生成已提交申请。</p><form className="filter-form" onSubmit={e=>{e.preventDefault();void operate('preview');}}><label>已有订单号<input required value={order} maxLength={100} disabled={busy || chat.busy} onChange={e=>setOrder(e.target.value)} placeholder="DEMO20261003002"/></label><label>具体申请原因<input required minLength={2} maxLength={500} value={reason} disabled={busy || chat.busy} onChange={e=>setReason(e.target.value)} placeholder="例如佩戴不合适"/></label><button className="primary" disabled={busy || chat.busy}>{busy?'正在处理…':'准备预览'}</button></form>{preview && (order && order.trim()!==preview.order_id || reason && reason.trim()!==preview.reason) && <p>输入已更改；下面仍是已保存的旧预览。请准备新预览后再确认。</p>}</section>}{error && <div className="error-panel" role="alert"><p>{error}</p><p>本次操作未完成，请检查状态后使用对应按钮显式重试。</p></div>}{preview && <AfterSalesPreview preview={preview} pending={busy || chat.busy || Boolean(form && ((order && order.trim()!==preview.order_id) || (reason && reason.trim()!==preview.reason)))} onConfirm={()=>operate('confirm')} onCancel={()=>operate('cancel')}/>}{form && <section className="context-card"><h2>售后预览与模拟申请记录</h2><button disabled={busy || chat.busy || recordsLoading} onClick={()=>void loadRecords()}>{recordsLoading?'读取中…':'刷新记录 / 重试'}</button>{recordsLoading && <p role="status">正在加载售后记录…</p>}{recordsError && <p role="alert">{recordsError}</p>}{!recordsLoading && !recordsError && records.length===0 && <p>暂无售后记录。</p>}{records.map(record=><details key={record.preview_id}><summary>{record.order_id} · {record.status==='submitted'?'模拟申请已保存':record.status==='pending'?'待确认':record.status==='expired'?'已过期':'已取消'} · ¥{(record.refund_amount_fen/100).toFixed(2)}</summary><p>{record.reason} · {record.explanation}</p><p>预览：{record.preview_id} {record.application_id && `申请：${record.application_id}`}</p></details>)}</section>}</>;
}
