/** 复用商品与已有订单详情抽屉。 */
import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
interface Props { open: boolean; title: string; children?: ReactNode; onClose: () => void; closeLabel?:string; dismissOnBackdrop?:boolean }
export function DetailDrawer({ open, title, onClose, children,closeLabel='关闭详情',dismissOnBackdrop=false }: Props) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    function handleKey(event: KeyboardEvent) {
      const dialogs=document.querySelectorAll('[aria-modal="true"]');
      if(dialogs[dialogs.length-1]!==panel.current) return;
      if (event.key === 'Escape') onClose();
      if (event.key === 'Tab') {
        const controls = panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)');
        if (!controls?.length) { event.preventDefault(); return; }
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || document.activeElement === panel.current)) { event.preventDefault(); first.focus(); }
      }
    }
    document.addEventListener('keydown', handleKey);
    return () => { document.removeEventListener('keydown', handleKey); previous?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return <div className="drawer-backdrop" onMouseDown={event=>{if(dismissOnBackdrop && event.target===event.currentTarget)onClose();}}><section ref={panel} tabIndex={-1} className="detail-drawer" role="dialog" aria-modal="true" aria-label={title}><div className="drawer-heading"><h2>{title}</h2><button onClick={onClose}>{closeLabel}</button></div>{children}</section></div>;
}
