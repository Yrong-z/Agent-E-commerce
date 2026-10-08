"""当前阶段有限检查：基础设施、O2 回归与尚未实现接口。"""
import argparse
import asyncio
import importlib
import json
import pkgutil
import sys
from datetime import datetime, timezone
from importlib.metadata import version
import httpx
import app
from app.config import PROJECT_ROOT
from app import db
from app.schemas import HealthResponse, ApiError, Product, Order, Comparison
from app.config import get_settings
from scripts.seed_demo import seed_demo_data, SEED_SOURCE
from app.services.orders import get_order, get_logistics
from app.adapters.commerce import MockCommerceAdapter

async def main(api_url: str, web_url: str) -> None:
    """执行检查并保存真实结果；任何失败返回非零退出码。"""
    checks = []
    async def record(name, operation):
        try:
            detail = await operation()
            checks.append({'name': name, 'status': 'passed', 'detail': detail})
        except Exception as error:
            checks.append({'name': name, 'status': 'failed', 'error': type(error).__name__})
    async def imports():
        modules = [module.name for module in pkgutil.walk_packages(app.__path__, app.__name__ + '.')]
        for module in modules:
            importlib.import_module(module)
        return {'imported_modules': len(modules)}
    await record('module_imports', imports)
    async def database():
        await db.open_pool()
        try:
            await db.init_schema()
            connected, vector = await db.check_database()
            assert connected and vector
            async with db.get_connection() as connection:
                cursor = await connection.execute("SELECT version(), (SELECT extversion FROM pg_extension WHERE extname='vector')")
                postgres_version, vector_version = await cursor.fetchone()
                cursor = await connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                tables = [row[0] for row in await cursor.fetchall()]
                assert set(['products','orders','sessions','knowledge_chunks','after_sales','traces']).issubset(tables)
            return {'postgresql': postgres_version, 'pgvector': vector_version, 'tables': tables}
        finally:
            await db.close_pool()
    await record('database_and_pgvector', database)
    async def seed_idempotency():
        await db.open_pool()
        try:
            async def snapshot():
                async with db.get_connection() as connection:
                    result = {}
                    for table, key in [('products','product_id'),('orders','order_id')]:
                        cursor = await connection.execute(f"SELECT {key},payload FROM {table} WHERE payload->>'_seed_source' IS DISTINCT FROM %s ORDER BY {key}", (SEED_SOURCE,))
                        result[table] = await cursor.fetchall()
                    return result
            others = await snapshot()
            counts = []
            for _ in range(2):
                await seed_demo_data()
                async with db.get_connection() as connection:
                    cursor = await connection.execute("SELECT (SELECT count(*) FROM products WHERE payload->>'_seed_source'=%s),(SELECT count(*) FROM orders WHERE payload->>'_seed_source'=%s)", (SEED_SOURCE,SEED_SOURCE))
                    counts.append(await cursor.fetchone())
            assert counts[0] == counts[1] == (12,3)
            assert others == await snapshot()
            order = await get_order('DEMO20261003001',get_settings().demo_customer_id)
            assert await get_logistics(order.order_id,get_settings().demo_customer_id) == order.logistics
            assert await MockCommerceAdapter().read_logistics(order.order_id) == order.logistics
            try:
                await get_order(order.order_id,'another-customer')
                raise AssertionError('应拒绝其他顾客订单')
            except Exception as error:
                assert getattr(error,'code',None) == 'ORDER_NOT_FOUND'
            return {'products':12,'orders':3,'repeat_runs':2,'other_records_preserved':True,'logistics_service':'passed','customer_isolation':'passed'}
        finally:
            await db.close_pool()
    await record('seed_and_services',seed_idempotency)
    async with httpx.AsyncClient(timeout=10) as client:
        async def health():
            response = await client.get(api_url + '/api/health')
            parsed = HealthResponse.model_validate(response.json())
            assert response.status_code == 200 and parsed.status == 'ok'
            return parsed.model_dump()
        await record('api_health', health)
        async def contracts():
            routes = [
                ('GET', '/evaluations/latest', None), ('GET', '/capabilities', None),
            ]
            for method, path, body in routes:
                response = await client.request(method, api_url + '/api' + path, json=body)
                assert response.status_code == 501
                assert ApiError.model_validate(response.json()).code == 'NOT_IMPLEMENTED'
            invalid = await client.post(api_url + '/api/products/compare', json={'product_ids':['one']})
            assert invalid.status_code == 422 and ApiError.model_validate(invalid.json()).code == 'INVALID_ARGUMENT'
            return {'unimplemented_routes': len(routes), 'all_status': 501, 'validation_status': 422}
        await record('http_contracts', contracts)
        async def catalog():
            response = await client.get(api_url + '/api/products', params={'budget_max_fen':30000,'use_case':'通勤','in_stock_only':True})
            assert response.status_code == 200
            products = [Product.model_validate(item) for item in response.json()]
            assert [p.product_id for p in products] == ['DEMO-A1','DEMO-B2','DEMO-F6']
            assert all(p.sale_price_fen <= 30000 and p.stock > 0 and '通勤' in p.use_cases for p in products)
            assert (products[0].sale_price_fen,products[0].stock) == (19900,48)
            assert (products[1].list_price_fen,products[1].discount_fen,products[1].sale_price_fen,products[1].stock) == (29900,2000,27900,26)
            response = await client.get(api_url + '/api/products',params={'budget_max_fen':20000,'use_case':'通勤','in_stock_only':True})
            assert [p['product_id'] for p in response.json()] == ['DEMO-A1']
            response = await client.get(api_url + '/api/products',params={'query':'DEMO-D4','in_stock_only':False})
            assert response.status_code == 200 and response.json()[0]['stock'] == 0
            response = await client.get(api_url + '/api/products',params={'budget_max_fen':1})
            assert response.status_code == 200 and response.json() == []
            response = await client.get(api_url + '/api/products/DEMO-F6')
            assert response.status_code == 200 and Product.model_validate(response.json()).specs.anc is None
            response = await client.post(api_url + '/api/products/compare',json={'product_ids':['DEMO-A1','DEMO-F6']})
            assert response.status_code == 200
            comparison = Comparison.model_validate(response.json())
            assert comparison.product_ids == ['DEMO-A1','DEMO-F6']
            assert next(row for row in comparison.rows if row.field=='anc').values == [False,None]
            for method,path,body,code in [
                ('GET','/products/NOT-FOUND',None,'PRODUCT_NOT_FOUND'),
                ('POST','/products/compare',{'product_ids':['DEMO-A1','NOT-FOUND']},'PRODUCT_NOT_FOUND'),
                ('GET','/orders/NOT-FOUND',None,'ORDER_NOT_FOUND'),
            ]:
                response = await client.request(method,api_url+'/api'+path,json=body)
                assert response.status_code == 404 and ApiError.model_validate(response.json()).code == code
            response = await client.get(api_url+'/api/orders')
            assert response.status_code == 200
            orders = [Order.model_validate(item) for item in response.json()]
            assert [o.order_id for o in orders] == ['DEMO20261003001','DEMO20261003002','DEMO20261003003']
            assert [o.paid_total_fen for o in orders] == [19900,27900,47900]
            for order in orders:
                response = await client.get(api_url+'/api/orders/'+order.order_id)
                assert response.status_code == 200 and Order.model_validate(response.json()) == order
            assert orders[0].logistics.summary == '快件已到达配送站'
            assert orders[0].status == 'shipped' and orders[0].signed_at is None
            today = datetime.now(timezone.utc).date()
            assert (today-orders[1].signed_at.date()).days == 2 and (today-orders[2].signed_at.date()).days == 10
            return {'implemented_http_routes':5,'prices':'passed','budget_and_stock':'passed','empty_result':'passed','unknown_specs':'passed','comparison':'passed','order_snapshot_and_logistics':'passed','not_found':404}
        await record('catalog_and_orders_http',catalog)
        async def frontend():
            response = await client.get(web_url)
            assert response.status_code == 200 and 'id="root"' in response.text
            response = await client.get(web_url + '/api/health')
            assert response.status_code == 200 and HealthResponse.model_validate(response.json()).status == 'ok'
            return {'frontend_http': 200, 'proxy_health': 200}
        await record('frontend_and_proxy', frontend)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'scope':'O3_infrastructure_and_O2_regression_only', 'environment': {name:version(name) for name in ['fastapi','pydantic','mcp','openai','psycopg','pgvector']}, 'checks':checks}
    # 保留原框架报告作为内部历史，不覆盖或冒充最终完整验收。
    (PROJECT_ROOT / 'artifacts' / 'o4-regression-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if any(check['status'] == 'failed' for check in checks):
        sys.exit(1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='检查基础设施、O2 回归及仍为 501 的接口；O3 使用 check_agent 补充')
    parser.add_argument('--api-url', default='http://127.0.0.1:8000')
    parser.add_argument('--web-url', default='http://127.0.0.1:5173')
    arguments = parser.parse_args()
    asyncio.run(main(arguments.api_url, arguments.web_url), loop_factory=db.create_event_loop)
