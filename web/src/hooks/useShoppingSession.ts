/** 会话、有限显示消息和后端事实状态；网络重试沿用消息 ID。 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { createSession, sendMessage, fetchSessions, fetchSession, ApiRequestError, deleteSession, deleteSessions, deleteAllSessions } from '../api';
import type { ChatRequest, ChatResponse, SessionResponse, SessionSummary, ViewState } from '../types';
export interface DisplayMessage { role: string; content: string; status?: string }
export function useShoppingSession() {
  const [sessionId,setSessionId] = useState<string | null>(null);
  const [sessions,setSessions] = useState<SessionSummary[]>([]);
  const [messages,setMessages] = useState<DisplayMessage[]>([]);
  const [viewState,setViewState] = useState<ViewState | null>(null);
  const [busy,setBusy] = useState(false), [error,setError] = useState(''), [sessionsError,setSessionsError] = useState('');
  const [draft,setDraft] = useState('');
  const [sessionNotice,setSessionNotice] = useState(''),[sessionTitle,setSessionTitle]=useState('');
  const [restoreError,setRestoreError]=useState(''), [restoreTarget,setRestoreTarget]=useState<string|null>(null);
  const busyRef = useRef(false), version = useRef(0), attempt = useRef<ChatRequest | null>(null);
  /** 删除或识别不存在时清除整份当前状态，不受已占用的请求锁阻止。 */
  const resetSession = useCallback(() => {
    ++version.current; attempt.current=null; setSessionId(null); setSessionTitle(''); setMessages([]); setViewState(null); setError(''); setRestoreError(''); setRestoreTarget(null); setDraft(''); localStorage.removeItem('shopping-session');
  },[]);
  const missingSession = useCallback((reason:unknown) => {
    if(reason instanceof ApiRequestError && reason.error.code==='SESSION_NOT_FOUND') {
      resetSession(); setSessionNotice('该会话已删除或不存在，已回到新会话。'); return true;
    }
    return false;
  },[resetSession]);
  const refreshSessions = useCallback(async () => {
    try { setSessions(await fetchSessions()); setSessionsError(''); }
    catch (reason) { setSessionsError(reason instanceof Error ? reason.message : '会话列表读取失败'); }
  },[]);
  const restoreSession = useCallback(async (id: string): Promise<SessionResponse | undefined> => {
    if (busyRef.current) return;
    busyRef.current=true; setBusy(true); setError(''); setRestoreError(''); setRestoreTarget(id); const current=++version.current;
    try {
      const result=await fetchSession(id);
      if (current===version.current) { setSessionId(id); setSessionTitle(result.state.title); setSessionNotice(''); setViewState(result.view_state); setMessages(result.state.display_messages); setDraft(result.state.display_messages.at(-1)?.status==='failed' ? result.state.display_messages.at(-2)?.content || '' : ''); setError(result.state.display_messages.at(-1)?.status==='failed' ? result.state.display_messages.at(-1)?.content || '本次聊天未完成' : ''); attempt.current=null; localStorage.setItem('shopping-session',id); }
      return result;
    } catch (reason) { if (current===version.current && !missingSession(reason)) setRestoreError(reason instanceof Error ? reason.message : '恢复失败'); }
    finally { busyRef.current=false; setBusy(false); }
  },[missingSession]);
  useEffect(() => { void refreshSessions(); const saved=localStorage.getItem('shopping-session'); if(saved) void restoreSession(saved); },[refreshSessions,restoreSession]);
  /** 新建仅清除本地视图，第一条实际消息建立新记录。 */
  function startNewSession() {
    if (busyRef.current) return;
    resetSession(); setSessionNotice('');
  }
  /** 同源标签通知与回到页面时的存在性检查，不用最近二十条判断历史是否删除。 */
  useEffect(() => {
    function deleted(event:StorageEvent) {
      if(event.key!=='shopping-session-deleted' || !event.newValue) return;
      try {const data=JSON.parse(event.newValue); if(data.all || data.ids?.includes(sessionId)){resetSession();setSessionNotice('会话已在另一个标签页删除，已回到新会话。');} void refreshSessions();} catch { /* 非本应用通知忽略。 */ }
    }
    async function checkCurrent() {
      if(!sessionId || busyRef.current) return;
      const current=version.current;
      try {await fetchSession(sessionId);} catch(reason){if(current===version.current && missingSession(reason)) void refreshSessions();}
    }
    window.addEventListener('storage',deleted); window.addEventListener('focus',checkCurrent);
    return()=>{window.removeEventListener('storage',deleted);window.removeEventListener('focus',checkCurrent);};
  },[sessionId,resetSession,missingSession,refreshSessions]);
  /** 删除失败不改变列表/当前状态；成功后同步恢复入口及跨标签通知。 */
  async function removeSessions(ids:string[]|null,expectedCount=0) {
    if(busyRef.current) throw new Error('会话正在处理，请稍后重试删除');
    busyRef.current=true;setBusy(true);
    try {
      const result=ids===null ? await deleteAllSessions(expectedCount) : ids.length===1 ? await deleteSession(ids[0]) : await deleteSessions(ids);
      if(ids===null || sessionId && ids.includes(sessionId)) {resetSession();setSessionNotice('会话已删除，已回到新会话。');}
      setSessions(previous=>ids===null ? [] : previous.filter(item=>!ids.includes(item.session_id)));
      localStorage.setItem('shopping-session-deleted',JSON.stringify({ids:ids??[],all:ids===null,at:crypto.randomUUID()}));
      await refreshSessions();return result;
    } finally {busyRef.current=false;setBusy(false);}
  }
  async function submitMessage(message=draft): Promise<ChatResponse | undefined> {
    if (busyRef.current || !message.trim()) return;
    busyRef.current=true; setBusy(true); setError(''); const current=version.current;
    if (!attempt.current || attempt.current.message!==message || (attempt.current.session_id && attempt.current.session_id!==sessionId)) {
      attempt.current={session_id:sessionId,message,client_message_id:crypto.randomUUID()};
    }
    try {
      const result=await sendMessage(attempt.current);
      if (current!==version.current) return result;
      setSessionId(result.session_id); setViewState(result.view_state);
      setMessages(previous=>{
        const retry=previous.at(-1)?.status==='failed' && previous.at(-2)?.role==='user' && previous.at(-2)?.content===message;
        const prefix=retry ? previous.slice(0,-1) : [...previous,{role:'user',content:message}];
        return [...prefix,{role:'assistant',content:result.answer,status:result.status}].slice(-24);
      });
      localStorage.setItem('shopping-session',result.session_id); attempt.current=null;
      if (result.status==='failed') { setError(result.error?.message || '本次聊天未完成'); setDraft(message); }
      else setDraft('');
      await refreshSessions();
      return result;
    } catch (reason) {
      // 未拿到响应时保留原 session_id（包括 null）与 client_message_id，防止重复执行。
      if(!missingSession(reason)){setError(reason instanceof Error ? reason.message : '聊天请求失败，请重试'); setDraft(message);}
    } finally { busyRef.current=false; setBusy(false); }
  }
  /** 专用售后接口与聊天共享等待锁，操作期间禁止新建/恢复/发送。 */
  async function performAfterSalesAction(operation:(id:string)=>Promise<unknown>) {
    if(busyRef.current) throw new Error('会话正在处理，请稍后重试');
    busyRef.current=true;setBusy(true);
    let id=sessionId;
    try {
      if(!id){const created=await createSession();id=created.state.session_id;setSessionId(id);localStorage.setItem('shopping-session',id);}
      return await operation(id);
    } finally {
      try {if(id){try{const restored=await fetchSession(id);setViewState(restored.view_state);setMessages(restored.state.display_messages);await refreshSessions();}catch(reason){if(!missingSession(reason)) throw reason;}}}
      finally{busyRef.current=false;setBusy(false);}
    }
  }
  return { sessionId,sessionTitle,sessions,messages,viewState,busy,error,sessionsError,restoreError,restoreTarget,draft,setDraft,sessionNotice,removeSessions,performAfterSalesAction,submitMessage,startNewSession,restoreSession,refreshSessions };
}
