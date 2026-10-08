/** 最近项菜单与分页管理，复用已有抽屉/会话钩子，不创建另一份会话状态。 */
import { useCallback,useEffect,useRef,useState } from 'react';
import type { SessionSummary,SessionPage } from '../types';
import { fetchSessionPage } from '../api';
import type { useShoppingSession } from '../hooks/useShoppingSession';
import { DetailDrawer } from './DetailDrawer';

export function SessionItem({session,current=false,busy,onRestore,onDelete,showUpdated=false}:{session:SessionSummary;showUpdated?:boolean;current?:boolean;busy:boolean;onRestore:(id:string)=>void;onDelete:(session:SessionSummary)=>void}) {
  const [menu,setMenu]=useState(false),container=useRef<HTMLDivElement>(null),trigger=useRef<HTMLButtonElement>(null),action=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    if(!menu)return;
    action.current?.focus();
    function outside(event:PointerEvent){if(!container.current?.contains(event.target as Node))setMenu(false);}
    document.addEventListener('pointerdown',outside);
    return()=>document.removeEventListener('pointerdown',outside);
  },[menu]);
  return <div ref={container} className="session-item" onContextMenu={event=>{event.preventDefault();if(!busy)setMenu(true);}}>
    <button className="session-open" title={session.title} disabled={busy} aria-current={current?'true':undefined} onClick={()=>{setMenu(false);onRestore(session.session_id);}}>{showUpdated?<><strong>{session.title}</strong><time dateTime={session.updated_at}>{new Date(session.updated_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}（北京时间）</time></>:session.title}</button>
    <button ref={trigger} className="session-more" disabled={busy} aria-label={`会话操作：${session.title}`} aria-haspopup="menu" aria-expanded={menu} onClick={()=>setMenu(value=>!value)}>⋯</button>
    {menu && <div role="menu" className="session-menu" onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();setMenu(false);trigger.current?.focus();}}}><button ref={action} role="menuitem" onClick={()=>{setMenu(false);onDelete(session);}}>删除会话</button></div>}
  </div>;
}

type Confirmation={ids:string[]|null;titles:string[];count:number};
export function SessionManager({open,single,onClose,onRestore,chat}:{open:boolean;single:SessionSummary|null;onClose:()=>void;onRestore:(id:string)=>void;chat:ReturnType<typeof useShoppingSession>}) {
  const [page,setPage]=useState<SessionPage|null>(null),[selected,setSelected]=useState<string[]>([]),[loading,setLoading]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [confirmation,setConfirmation]=useState<Confirmation|null>(null),[deleting,setDeleting]=useState(false);
  const working=useRef(false),version=useRef(0);
  const loadPage=useCallback(async(offset=0)=>{
    const current=++version.current;setLoading(true);setError('');
    try{
      let result=await fetchSessionPage(offset);
      if(!result.items.length && result.total && offset)result=await fetchSessionPage(Math.floor((result.total-1)/20)*20);
      if(current===version.current){setPage(result);setSelected([]);}
    }catch(reason){if(current===version.current)setError(reason instanceof Error?reason.message:'会话列表读取失败');}
    finally{if(current===version.current)setLoading(false);}
  },[]);
  useEffect(()=>{if(open){setConfirmation(null);setNotice('');void loadPage();}return()=>{++version.current;};},[open,loadPage]);
  useEffect(()=>{if(single){setError('');setNotice('');setConfirmation({ids:[single.session_id],titles:[single.title],count:1});}},[single]);
  const close=useCallback(()=>{if(!working.current){setConfirmation(null);onClose();}},[onClose]);
  async function prepareAll(){
    if(loading || working.current)return;
    setLoading(true);setError('');
    try{const actual=await fetchSessionPage(0,1);setConfirmation({ids:null,titles:[],count:actual.total});}
    catch(reason){setError(reason instanceof Error?reason.message:'会话数量读取失败');}
    finally{setLoading(false);}
  }
  async function confirm(){
    if(!confirmation || working.current)return;
    working.current=true;setDeleting(true);setError('');
    try{
      const result=await chat.removeSessions(confirmation.ids,confirmation.count);
      setNotice(`实际删除 ${result.deleted_count} 条会话${result.not_found_ids.length?`，${result.not_found_ids.length} 条已不存在`:''}。`);
      setConfirmation(null);setSelected([]);
      if(open)await loadPage(page?.offset??0);else onClose();
    }catch(reason){setError(reason instanceof Error?reason.message:'删除失败，请重试');}
    finally{working.current=false;setDeleting(false);}
  }
  const disabled=chat.busy || deleting || loading;
  return <DetailDrawer open={open || Boolean(single)} title={open?'会话管理':'删除会话'} closeLabel={open?'关闭会话管理':'取消删除'} onClose={close} dismissOnBackdrop>
    <p className="muted">只删除聊天与会话状态，不删除商品、订单、知识库或售后记录。删除不可恢复；无法可靠归属的旧执行日志仍保留。</p>
    {notice && <p role="status">{notice}</p>}
    {confirmation ? <section className="session-confirm"><h3>{confirmation.ids===null?'确认删除全部会话？':'确认删除所选会话？'}</h3>
      {confirmation.ids===null ? <p>将删除当前演示用户的全部 <strong>{confirmation.count}</strong> 条会话，包括未加载的历史记录。此操作不可恢复。</p> : <><p>将删除以下 {confirmation.count} 条会话，此操作不可恢复：</p><ul>{confirmation.titles.map((title,index)=><li key={index}>{title}</li>)}</ul></>}
      {error && <p role="alert">{error}</p>}
      <div className="result-toolbar"><button className="danger" disabled={disabled || confirmation.count===0} onClick={()=>void confirm()}>{deleting?'正在删除…':error?'重试删除':confirmation.ids===null?'确认删除全部会话':'确认删除'}</button><button disabled={deleting} onClick={()=>{setConfirmation(null);setError('');if(!open)onClose();}}>取消</button>{confirmation.ids===null && error && <button disabled={disabled} onClick={()=>void prepareAll()}>刷新数量并重新确认</button>}</div>
    </section> : <>
      <div className="result-toolbar"><p>全部 {page?.total??'待检查'} 条 · 已选 {selected.length} 条</p><button className="danger" disabled={disabled || selected.length===0} onClick={()=>{setError('');setConfirmation({ids:selected,titles:page?.items.filter(item=>selected.includes(item.session_id)).map(item=>item.title)??[],count:selected.length});}}>删除所选会话</button></div>
      <label className="session-select-all"><input type="checkbox" disabled={disabled || !page?.items.length} checked={Boolean(page?.items.length && selected.length===page.items.length)} onChange={event=>setSelected(event.target.checked?page?.items.map(item=>item.session_id)??[]:[])}/>全选当前页（最多20条）</label>
      {loading && <p role="status">正在读取会话…</p>}{error && <div role="alert"><p>{error}</p><button disabled={disabled} onClick={()=>void loadPage(page?.offset??0)}>重试读取</button></div>}
      {!loading && page?.total===0 && <p>暂无已保存会话。</p>}
      <div className="session-management-list">{page?.items.map(item=><article key={item.session_id}><label><input aria-label={`选择会话：${item.title}`} type="checkbox" disabled={disabled} checked={selected.includes(item.session_id)} onChange={event=>setSelected(current=>event.target.checked?[...current,item.session_id]:current.filter(id=>id!==item.session_id))}/></label><SessionItem showUpdated session={item} current={chat.sessionId===item.session_id} busy={disabled} onRestore={id=>{close();onRestore(id);}} onDelete={session=>{setError('');setConfirmation({ids:[session.session_id],titles:[session.title],count:1});}}/></article>)}</div>
      <div className="result-toolbar"><button disabled={disabled || !page?.offset} onClick={()=>void loadPage(Math.max(0,(page?.offset??0)-20))}>上一页</button><span>第 {Math.floor((page?.offset??0)/20)+1} 页 / {Math.max(1,Math.ceil((page?.total??0)/20))} 页</span><button disabled={disabled || !page?.has_more} onClick={()=>void loadPage((page?.offset??0)+20)}>下一页</button></div>
      <div className="session-all-delete"><button className="danger" disabled={disabled || page?.total===0} onClick={()=>void prepareAll()}>删除全部会话</button><p>覆盖当前用户所有会话，不仅是当前页。</p></div>
    </>}
  </DetailDrawer>;
}
