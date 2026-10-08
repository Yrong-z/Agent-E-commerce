"""商业系统读取边界；当前实际读取合成演示数据库。"""
from typing import Any, Protocol
from app.schemas import Order, Logistics, DomainError
from app.db import get_connection
from app.config import get_settings

class CommerceAdapter(Protocol):
    """替换企业 REST/ERP 数据时的三个读取契约。"""
    async def read_products(self) -> list[dict[str, Any]]:
        """商品原始记录读取契约。"""
        ...
    async def read_order(self, order_id: str, customer_id: str) -> Order:
        """按顾客归属读取已有订单的契约。"""
        ...
    async def read_logistics(self, order_id: str) -> Logistics:
        """已有订单物流读取契约。"""
        ...

class MockCommerceAdapter:
    """读取项目演示数据库；没有连接真实商家或企业系统。"""
    async def read_products(self) -> list[dict[str, Any]]:
        """按稳定 ID 顺序读取商品原始记录，移除内部种子标记。"""
        async with get_connection() as connection:
            cursor = await connection.execute('SELECT payload FROM products ORDER BY product_id')
            return [{key: value for key, value in row[0].items() if key != '_seed_source'} for row in await cursor.fetchall()]
    async def read_order(self, order_id: str, customer_id: str) -> Order:
        """按 ID 和顾客归属读取订单快照，不存在和不属于均明确失败。"""
        async with get_connection() as connection:
            cursor = await connection.execute('SELECT payload FROM orders WHERE order_id = %s AND customer_id = %s', (order_id, customer_id))
            row = await cursor.fetchone()
        if row is None:
            raise DomainError('ORDER_NOT_FOUND', '未找到当前演示用户的已有订单')
        return Order.model_validate({key:value for key,value in row[0].items() if key != '_seed_source'})
    async def read_logistics(self, order_id: str) -> Logistics:
        """读取当前演示用户物流，不接受模型指定其他顾客。"""
        return (await self.read_order(order_id, get_settings().demo_customer_id)).logistics
