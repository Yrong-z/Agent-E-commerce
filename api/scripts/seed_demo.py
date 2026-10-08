"""幂等初始化合成耳机与三个已有演示订单，不清空其他记录。"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from psycopg.types.json import Jsonb
from app import db
from app.config import PROJECT_ROOT, get_settings
from app.schemas import Product, Order
from app.services.pricing import calculate_offer

SEED_SOURCE = 'shopping-assistant-demo-v1'

async def seed_demo_data() -> None:
    """仅插入指定演示 ID，冲突时只更新本来源已拥有的记录。"""
    raw_products = json.loads((PROJECT_ROOT / 'data/products.json').read_text(encoding='utf-8'))
    raw_orders = json.loads((PROJECT_ROOT / 'data/orders.json').read_text(encoding='utf-8'))
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    products = [Product.model_validate({**record, **calculate_offer(record['list_price_fen'], record['promotion_eligible']).model_dump()}) for record in raw_products]
    if not 10 <= len(products) <= 20 or len({p.product_id for p in products}) != len(products) or any(not p.product_id.startswith('DEMO-') for p in products):
        raise ValueError('商品种子必须是 10–20 个不同的 DEMO- ID')
    orders = []
    for raw in raw_orders:
        record = raw.copy()
        days = record.pop('signed_days_ago')
        signed_at = (now - timedelta(days=days)).astimezone(timezone.utc) if days is not None else None
        record['signed_at'] = signed_at
        record['customer_id'] = get_settings().demo_customer_id
        record['logistics'] = {'summary': record['logistics']['summary'], 'events': [{'time': signed_at or (now - timedelta(hours=3)).astimezone(timezone.utc), 'description': record['logistics']['summary']}]}
        orders.append(Order.model_validate(record))
    if {order.order_id for order in orders} != {'DEMO20261003001','DEMO20261003002','DEMO20261003003'}:
        raise ValueError('订单种子必须是规定的三个演示 ID')
    async with db.get_connection() as connection:
        for product in products:
            payload = {**product.model_dump(mode='json'), '_seed_source':SEED_SOURCE}
            await connection.execute("INSERT INTO products(product_id,payload) VALUES (%s,%s) ON CONFLICT(product_id) DO UPDATE SET payload=EXCLUDED.payload WHERE products.payload->>'_seed_source' = %s", (product.product_id,Jsonb(payload),SEED_SOURCE))
        for order in orders:
            payload = {**order.model_dump(mode='json'), '_seed_source':SEED_SOURCE}
            await connection.execute("INSERT INTO orders(order_id,customer_id,payload) VALUES (%s,%s,%s) ON CONFLICT(order_id) DO UPDATE SET customer_id=EXCLUDED.customer_id,payload=EXCLUDED.payload WHERE orders.payload->>'_seed_source' = %s AND orders.customer_id=EXCLUDED.customer_id", (order.order_id,order.customer_id,Jsonb(payload),SEED_SOURCE))

async def main() -> None:
    """使用现有连接配置初始化表与种子，退出时关闭连接池。"""
    await db.open_pool()
    try:
        await db.init_schema()
        await seed_demo_data()
        print('演示种子初始化完成；只处理本项目来源记录')
    finally:
        await db.close_pool()

if __name__ == '__main__':
    asyncio.run(main(), loop_factory=db.create_event_loop)
