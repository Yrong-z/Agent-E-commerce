"""官方 MCP SDK stdio 服务；只读复用商品与当前演示用户订单服务。"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field, StrictBool
from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout

from app import db
from app.config import get_settings
from app.schemas import DomainError, Order, Product
from app.services import catalog, orders

logger = logging.getLogger(__name__)


@asynccontextmanager
async def database_lifespan(server: FastMCP):
    """仅管理连接池，不初始化表、不写入种子或会话。"""
    await db.open_pool()
    logger.info('MCP database pool opened')
    try:
        yield
    finally:
        await db.close_pool()
        logger.info('MCP database pool closed')


async def search_products(
    query: str = '',
    budget_max_fen: Annotated[int | None, Field(ge=0, strict=True)] = None,
    use_case: str | None = None,
    in_stock_only: StrictBool = True,
    limit: Annotated[int, Field(ge=1, le=6, strict=True)] = 6,
) -> list[Product]:
    """只读查询合成演示商品；预算为整数分，空结果返回空列表。"""
    try:
        return await catalog.search_products(query, budget_max_fen, use_case, in_stock_only, limit)
    except (DatabaseError, PoolTimeout, RuntimeError):
        raise ToolError('DEPENDENCY_UNAVAILABLE：演示数据库暂不可用，请稍后重试') from None


async def get_order(order_id: Annotated[str, Field(min_length=1)]) -> Order:
    """只读查询当前演示用户的已有订单；金额保留历史实付，不创建订单。"""
    if not order_id.strip():
        raise ToolError('INVALID_ARGUMENT：order_id 不能为空白')
    try:
        return await orders.get_order(order_id.strip(), get_settings().demo_customer_id)
    except DomainError as error:
        raise ToolError(f'{error.code}：{error.message}') from None
    except (DatabaseError, PoolTimeout, RuntimeError):
        raise ToolError('DEPENDENCY_UNAVAILABLE：演示数据库暂不可用，请稍后重试') from None


def create_mcp_server() -> FastMCP:
    """只注册两个实际只读工具，独立于原生工具调用 Agent。"""
    server = FastMCP('选购助手（合成演示数据，只读）', lifespan=database_lifespan)
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    server.add_tool(search_products, annotations=annotations, structured_output=True)
    server.add_tool(get_order, annotations=annotations, structured_output=True)
    return server


if __name__ == '__main__':
    # stdout 专用于 JSON-RPC；Windows 服务进程保持 psycopg 的 Selector 兼容方式。
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    asyncio.run(create_mcp_server().run_stdio_async(), loop_factory=db.create_event_loop)
