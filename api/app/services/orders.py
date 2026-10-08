"""演示用户已有订单与物流查询。"""
from app.schemas import Order, Logistics
from app.db import get_connection
from app.adapters.commerce import MockCommerceAdapter

async def list_customer_orders(customer_id: str) -> list[Order]:
    """读取当前用户已有订单快照，金额不按当前促销价重算。"""
    async with get_connection() as connection:
        cursor = await connection.execute('SELECT payload FROM orders WHERE customer_id = %s ORDER BY order_id', (customer_id,))
        records = await cursor.fetchall()
    return [Order.model_validate({key:value for key,value in row[0].items() if key != '_seed_source'}) for row in records]

async def get_order(order_id: str, customer_id: str) -> Order:
    """读取属于当前用户的已有订单及物流。"""
    return await MockCommerceAdapter().read_order(order_id, customer_id)

async def get_logistics(order_id: str, customer_id: str) -> Logistics:
    """从已校验顾客归属的订单快照读取物流。"""
    return (await get_order(order_id, customer_id)).logistics
