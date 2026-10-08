/** 顾客会话正文与明确等待/失败状态，不展示工具或隐藏推理。 */
import { useEffect, useRef, type FormEvent } from 'react';
import type { DisplayMessage } from '../hooks/useShoppingSession';
export function Conversation({messages,busy}:{messages:DisplayMessage[];busy:boolean}) {
  const area=useRef<HTMLElement>(null);
  useEffect(()=>{if(area.current) area.current.scrollTop=area.current.scrollHeight;},[messages,busy]);
  return <section ref={area} className="chat-conversation" aria-label="聊天记录" aria-live="polite">{messages.length===0 && <div className="welcome"><span className="eyebrow">你的选购助手</span><h2>描述预算和用途，继续追问详情</h2><p>例如：300 元内推荐两款有货通勤耳机。订单服务查询的是已有演示订单。</p></div>}{messages.map((message,index)=><div key={index} className={`chat-message ${message.role} ${message.status==='failed'?'failed':''}`}><strong>{message.role==='user'?'你':message.status==='failed'?'本次未完成':'选购助手'}</strong><p>{message.status==='failed'?'本轮未完成；请在输入区查看原因并显式重试。':message.content}</p></div>)}{busy && <p className="chat-wait" role="status">正在处理，请稍候…</p>}</section>;
}
interface ComposerProps { draft:string; onDraftChange:(value:string)=>void; onSubmit:()=>void; busy:boolean; available:boolean; unavailableReason:string; error:string }
export function MessageComposer({draft,onDraftChange,onSubmit,busy,available,unavailableReason,error}:ComposerProps) {
  function submit(event:FormEvent) { event.preventDefault(); if (!busy && available && draft.trim()) onSubmit(); }
  return <form className="composer" onSubmit={submit}><label htmlFor="message">描述需求或查询已有订单</label>{!available && <p className="chat-unavailable">{unavailableReason}</p>}<div className="composer-input"><textarea id="message" value={draft} onChange={event=>onDraftChange(event.target.value)} placeholder="例如：把预算改为200元，或查询已有订单物流" maxLength={2000} disabled={busy || !available}/><button type="submit" disabled={busy || !available || !draft.trim()} aria-label="发送消息">↑</button></div>{error && <div className="error-panel" role="alert"><p>{error}</p><button type="submit" disabled={busy || !available || !draft.trim()}>重试聊天</button></div>}<p>合成演示数据 · 售后需显式按钮确认 · 政策来自项目演示资料</p></form>;
}
