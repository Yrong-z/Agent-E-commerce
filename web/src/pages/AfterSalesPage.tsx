/** 复用会话及显式确认组件，刷新可恢复真实状态。 */
import { AfterSalesWorkspace } from '../components/AfterSalesWorkspace';
import type { useShoppingSession } from '../hooks/useShoppingSession';
export function AfterSalesPage({chat}:{chat:ReturnType<typeof useShoppingSession>}) {
  return <div className="after-sales-page"><AfterSalesWorkspace chat={chat} form/></div>;
}
