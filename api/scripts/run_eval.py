"""O7 二十案例：真实业务服务/HTTP Agent；不自动重试，历史报告只追加。"""
import argparse
import asyncio
import json
import platform
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from unittest.mock import patch
from uuid import uuid4
import httpx
from psycopg.types.json import Jsonb
from app import db
from app.config import PROJECT_ROOT, get_settings
from app.schemas import DomainError, EvalReport, SessionState
from app.agent.state import save_session
from app.services import catalog, orders, after_sales, knowledge
from app.services.pricing import calculate_offer


def require(condition, description):
    if not condition:
        raise AssertionError(description)


async def expect_error(action, code):
    try:
        await action
    except DomainError as error:
        require(error.code == code, f'expected {code}, got {error.code}')
    else:
        raise AssertionError(f'expected {code}, got success')


async def verify_hits(hits):
    require(bool(hits), 'nonempty real retrieval')
    async with db.get_connection() as connection:
        for hit in hits:
            cursor = await connection.execute('SELECT document_id,title,excerpt FROM knowledge_chunks WHERE chunk_id=%s AND source_owner=%s', (hit['chunk_id'], knowledge.SOURCE_OWNER))
            require(await cursor.fetchone() == (hit['document_id'], hit['title'], hit['excerpt']) and bool(hit['excerpt']), 'citation matches database chunk')


async def deterministic(case_id, evidence):
    customer = get_settings().demo_customer_id
    if case_id == 'D01':
        a, b = await catalog.get_product('DEMO-A1'), await catalog.get_product('DEMO-B2')
        require(a.sale_price_fen == 19900 and (b.list_price_fen, b.discount_fen, b.sale_price_fen) == (29900, 2000, 27900), 'seed prices')
        evidence.extend([a.model_dump(mode='json'), b.model_dump(mode='json')])
    elif case_id == 'D02':
        for price, eligible, discount, sale in [(19999, True, 0, 19999), (20000, True, 2000, 18000), (29900, False, 0, 29900)]:
            offer = calculate_offer(price, eligible)
            require((offer.discount_fen, offer.sale_price_fen) == (discount, sale), 'promotion threshold')
            evidence.append(offer.model_dump())
    elif case_id in {'D03', 'D04'}:
        products = await catalog.search_products(budget_max_fen=30000 if case_id == 'D03' else 1, use_case='通勤')
        require([p.product_id for p in products] == (['DEMO-A1', 'DEMO-B2', 'DEMO-F6'] if case_id == 'D03' else []), 'exact budget/stock results')
        if case_id == 'D03':
            require(all(p.stock > 0 and p.sale_price_fen <= 30000 for p in products), 'stock/current sale price')
            require((await catalog.search_products(query='DEMO-D4', budget_max_fen=30000, in_stock_only=False))[0].stock == 0, 'out of stock opt in')
        evidence.extend(p.model_dump(mode='json') for p in products)
    elif case_id == 'D05':
        comparison = await catalog.compare_products(['DEMO-A1', 'DEMO-F6'])
        require(comparison.product_ids == ['DEMO-A1', 'DEMO-F6'] and any(None in r.values for r in comparison.rows), 'unknown stays null')
        await expect_error(catalog.compare_products(['DEMO-A1', 'NOT-FOUND-O7']), 'PRODUCT_NOT_FOUND')
        evidence.append(comparison.model_dump(mode='json'))
    elif case_id == 'D06':
        templates = json.loads((PROJECT_ROOT / 'data/orders.json').read_text(encoding='utf-8'))
        for template in templates:
            order = await orders.get_order(template['order_id'], customer)
            require(order.customer_id == customer, 'configured customer ownership')
            for field in ('items', 'paid_total_fen', 'status', 'policy_id'):
                require(order.model_dump(mode='json')[field] == template[field], f'order seed {field}')
            logistics = await orders.get_logistics(order.order_id, customer)
            require(logistics == order.logistics and logistics.summary == template['logistics']['summary'], 'order/logistics seed facts')
            evidence.append(order.model_dump(mode='json'))
        await expect_error(orders.get_order('NOT-FOUND-O7', customer), 'ORDER_NOT_FOUND')
        await expect_error(orders.get_order(order.order_id, 'other-customer'), 'ORDER_NOT_FOUND')
    elif case_id in {'D07', 'D08', 'D09', 'D10'}:
        session_id = 'o7-eval-' + str(uuid4())
        await save_session(SessionState(session_id=session_id, updated_at=datetime.now(timezone.utc)), customer)
        try:
            if case_id == 'D08':
                original = db.get_connection
                async with original() as connection:
                    async with connection.transaction(force_rollback=True):
                        @asynccontextmanager
                        async def same_connection():
                            yield connection
                        with patch.object(db, 'get_connection', same_connection):
                            await connection.execute("UPDATE products SET payload=jsonb_set(payload,'{list_price_fen}','99900'::jsonb) WHERE product_id='DEMO-B2'")
                            preview = await after_sales.prepare_after_sales('DEMO20261003002', '佩戴不合适', session_id, customer)
                            require(preview.refund_amount_fen == 27900, 'historical paid amount despite changed current price')
                            evidence.append(preview.model_dump(mode='json'))
            else:
                preview = await after_sales.prepare_after_sales('DEMO20261003002', '佩戴不合适', session_id, customer)
                require(preview.eligible and preview.status == 'pending' and preview.application_id is None, 'eligible preview does not submit')
                if case_id == 'D07':
                    for order_id in ['DEMO20261003001', 'DEMO20261003003']:
                        await expect_error(after_sales.prepare_after_sales(order_id, '佩戴不合适', session_id, customer), 'INELIGIBLE')
                elif case_id == 'D09':
                    first = await after_sales.confirm_after_sales(preview.preview_id, session_id, customer)
                    second = await after_sales.confirm_after_sales(preview.preview_id, session_id, customer)
                    require(first.application_id == second.application_id and first.application_id is not None, 'same application')
                    async with db.get_connection() as connection:
                        cursor = await connection.execute('SELECT count(*) FROM after_sales WHERE preview_id=%s AND application_id IS NOT NULL', (preview.preview_id,))
                        require((await cursor.fetchone())[0] == 1, 'one application row')
                    evidence.append(first.model_dump(mode='json'))
                else:
                    await after_sales.cancel_after_sales(preview.preview_id, session_id, customer)
                    await expect_error(after_sales.confirm_after_sales(preview.preview_id, session_id, customer), 'STATE_CONFLICT')
                    expired = await after_sales.prepare_after_sales(preview.order_id, '续航不合适', session_id, customer)
                    expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                    async with db.get_connection() as connection:
                        await connection.execute('UPDATE after_sales SET payload=%s WHERE preview_id=%s', (Jsonb(expired.model_dump(mode='json')), expired.preview_id))
                    await expect_error(after_sales.confirm_after_sales(expired.preview_id, session_id, customer), 'PREVIEW_EXPIRED')
                evidence.append(preview.model_dump(mode='json'))
        finally:
            async with db.get_connection() as connection:
                await connection.execute('DELETE FROM after_sales WHERE session_id=%s', (session_id,))
                await connection.execute('DELETE FROM sessions WHERE session_id=%s', (session_id,))
    elif case_id == 'D11':
        hits = await knowledge.search_knowledge('签收后退货期限和条件')
        require(any(h.document_id == 'demo-policy-return' for h in hits), 'return source retrieved')
        await verify_hits([h.model_dump(mode='json') for h in hits])
        async with db.get_connection() as connection:
            cursor = await connection.execute('SELECT DISTINCT vector_dims(embedding),embedding_dimension FROM knowledge_chunks WHERE source_owner=%s', (knowledge.SOURCE_OWNER,))
            require(await cursor.fetchall() == [(get_settings().embedding_dimension, get_settings().embedding_dimension)], 'stored vector dimension')
        evidence.extend(h.model_dump(mode='json') for h in hits)
    elif case_id == 'D12':
        process = await asyncio.to_thread(subprocess.run, [sys.executable, '-m', 'pytest', 'tests/test_api_contract.py::test_sessions_restore_idempotency_conflict_and_concurrency', '-q'], cwd=PROJECT_ROOT / 'api', capture_output=True, text=True, timeout=60)
        evidence.append({'mode': 'real_database_asgi_with_local_model_fixture', 'output': process.stdout + process.stderr})
        require(process.returncode == 0, 'existing dedup/restore assertions')


async def online(case_id, client, evidence):
    session_id = None
    async def turn(message, expected_dependency_failure=False):
        nonlocal session_id
        response = await client.post('/api/chat', json={'session_id': session_id, 'message': message, 'client_message_id': str(uuid4())})
        require(response.status_code == 200, f'HTTP {response.status_code}')
        result = response.json()
        session_id = result['session_id']
        trace = (await client.get('/api/traces/' + result['request_id'])).json()
        restored = (await client.get('/api/sessions/' + session_id)).json()
        evidence.append({'message': message, 'response': result, 'trace': trace, 'state': restored['state']})
        if not expected_dependency_failure and result.get('error') and result['error']['code'].startswith(('MODEL_', 'EMBEDDING_', 'KNOWLEDGE_UNAVAILABLE')):
            raise DomainError(result['error']['code'], '在线依赖失败', 503)
        return result

    def tool(name, result):
        item = next(e for e in reversed(evidence) if e['response']['request_id'] == result['request_id'])
        require(any(e['tool_name'] == name and not e['error'] for e in item['trace']), f'actual successful {name}')
        calls = [call for m in item['state']['recent_messages'] for call in m.get('tool_calls', []) if call['function']['name'] == name]
        require(bool(calls), 'native tool call exists')
        call = calls[-1]
        reply = next(m for m in item['state']['recent_messages'] if m.get('tool_call_id') == call['id'])
        return json.loads(call['function']['arguments']), json.loads(reply['content'])

    if case_id in {'A01', 'A02', 'A03', 'A04'}:
        first = await turn('300元内推荐两款有货通勤耳机')
        args, result = tool('search_products', first)
        require(first['status'] == 'completed' and [p['product_id'] for p in first['view_state']['products']] == ['DEMO-A1', 'DEMO-B2'], 'two expected candidates')
        require(first['view_state']['products'] == result['data'], 'cards equal tool facts')
        for p in first['view_state']['products']:
            require(p == (await catalog.get_product(p['product_id'])).model_dump(mode='json'), 'cards equal database facts')
        constraints = first['view_state']['constraints']
        require(constraints['budget_max_fen'] == 30000 and constraints['use_case'] == '通勤' and constraints['in_stock_only'], 'search conditions')
        if case_id == 'A02':
            second = await turn('第二款详情')
            tool('get_product', second)
            require(second['status'] == 'completed' and second['view_state']['focused_product']['product_id'] == 'DEMO-B2', 'second candidate reference')
        elif case_id == 'A03':
            second = await turn('把预算改为200元')
            tool('search_products', second)
            require(second['status'] == 'completed' and [p['product_id'] for p in second['view_state']['products']] == ['DEMO-A1'] and second['view_state']['constraints']['use_case'] == '通勤' and second['view_state']['constraints']['in_stock_only'], 'budget retains conditions')
        elif case_id == 'A04':
            second = await turn('对比这两款，关注降噪')
            tool('compare_products', second)
            require(second['status'] == 'completed' and second['view_state']['comparison'] == (await catalog.compare_products(['DEMO-A1', 'DEMO-B2'])).model_dump(mode='json'), 'comparison real parameters')
    elif case_id == 'A05':
        first = await turn('查询我的已有订单物流')
        require(first['status'] == 'needs_input' and first['view_state']['order'] is None and first['answer'], 'ask missing order')
        second = await turn('DEMO20261003001')
        tool('get_logistics', second)
        require(second['status'] == 'completed' and second['view_state']['order'] == (await orders.get_order('DEMO20261003001', get_settings().demo_customer_id)).model_dump(mode='json'), 'correct order/logistics')
    elif case_id == 'A06':
        first = await turn('请检索演示政策：签收后退货期限和条件，不要创建申请')
        tool('search_knowledge', first)
        require(first['status'] == 'completed' and first['view_state']['after_sales_preview'] is None, 'consultation does not create application')
        await verify_hits(first['view_state']['citations'])
        second = await turn('请检索火星大气压资料；没有依据请明确无法确认，不要使用常识回答')
        tool('search_knowledge', second)
        require(second['status'] == 'completed' and not second['view_state']['citations'] and bool(second['answer']), 'no evidence/no citations')
        third = await turn('演示政策是否保证退货原运费和寄回费用都能报销？请检索，资料未覆盖时明确无法确认')
        tool('search_knowledge', third)
        if third['view_state']['citations']:
            await verify_hits(third['view_state']['citations'])
        require(third['status'] == 'completed', 'insufficient policy scope')
    elif case_id == 'A07':
        first = await turn('我要申请签收后退货')
        require(first['status'] == 'needs_input' and first['view_state']['after_sales_preview'] is None, 'missing after-sales information')
        second = await turn('订单DEMO20261003002，原因是佩戴不合适')
        tool('prepare_after_sales', second)
        preview = second['view_state']['after_sales_preview']
        require(second['status'] == 'completed' and preview['status'] == 'pending' and preview['refund_amount_fen'] == 27900, 'pending historical paid preview')
        await turn('先推荐200元内有货通勤耳机')
        fourth = await turn('继续刚才售后，我确认')
        require(fourth['view_state']['after_sales_preview']['preview_id'] == preview['preview_id'] and fourth['view_state']['after_sales_preview']['status'] == 'pending', 'same preview; chat cannot submit')
        require(all(e['tool_name'] != 'confirm_after_sales' for item in evidence for e in item['trace']), 'confirmation not model tool')
        confirmed = await client.post('/api/after-sales/' + preview['preview_id'] + '/confirm', json={'session_id': session_id})
        duplicate = await client.post('/api/after-sales/' + preview['preview_id'] + '/confirm', json={'session_id': session_id})
        require(confirmed.status_code == duplicate.status_code == 200 and confirmed.json()['application_id'] == duplicate.json()['application_id'] and confirmed.json()['status'] == 'submitted', 'explicit endpoint idempotent')
        evidence.append({'explicit_http_confirmation': confirmed.json(), 'user_button_evidence': 'O5 ui-demo-check.json'})
    elif case_id == 'A08':
        # 单个ASGI请求内的受控替身，只让真实在线模型选中的检索工具失败。
        # 实际数据库/TEI/运行中的API均不停止，不替换模型响应或向量。
        from app.main import app
        async def fail_embedding(*args, **kwargs):
            raise DomainError('EMBEDDING_FAILED', 'O7 controlled one-request dependency failure', 503)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://o7-test', timeout=65) as local_client:
            client = local_client
            with patch.object(knowledge, '_embed', fail_embedding):
                failed = await turn('请检索演示签收后退货政策，不要创建申请', expected_dependency_failure=True)
            require(failed['status'] == 'failed' and failed['error']['code'] == 'EMBEDDING_FAILED' and not failed['view_state']['citations'], 'injected tool failure cannot fabricate success/citations')
            require(any(e['error'] == 'EMBEDDING_FAILED' for e in evidence[-1]['trace']), 'failure trace')
            recovered = await turn('重新检索演示签收后退货政策，不要创建申请')
            tool('search_knowledge', recovered)
            require(recovered['status'] == 'completed', 'explicit retry with real embedding')
            await verify_hits(recovered['view_state']['citations'])


async def run_evaluation(case_ids=None, api_url='http://127.0.0.1:8000') -> EvalReport:
    definitions = [json.loads(line) for line in (PROJECT_ROOT / 'data/eval_cases.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    require(len(definitions) == 20 and len({c['case_id'] for c in definitions}) == 20, 'twenty unique cases')
    if case_ids:
        require(set(case_ids) <= {c['case_id'] for c in definitions}, 'unknown case ID')
        definitions = [c for c in definitions if c['case_id'] in case_ids]
    settings = get_settings()
    cases = []
    await db.open_pool()
    try:
        async with httpx.AsyncClient(base_url=api_url, timeout=65, trust_env=False) as client:
            for definition in definitions:
                evidence = []
                started = monotonic()
                case = {**definition, 'evidence': evidence}
                try:
                    if definition['case_id'].startswith('A'):
                        if not all((settings.chat_model, settings.chat_base_url, settings.chat_api_key.get_secret_value())):
                            case.update(status='not_run', failure_kind='environment', error='CHAT configuration missing')
                        else:
                            await online(definition['case_id'], client, evidence)
                    else:
                        await deterministic(definition['case_id'], evidence)
                    case.setdefault('status', 'passed')
                except Exception as error:
                    environment = isinstance(error, (httpx.HTTPError, OSError)) or (isinstance(error, DomainError) and error.code.startswith(('MODEL_', 'EMBEDDING_', 'KNOWLEDGE_'))) or type(error).__module__.startswith('psycopg')
                    case.update(status='failed', failure_kind='environment' if environment else 'business_or_assertion', error=error.code if isinstance(error, DomainError) else str(error) if isinstance(error, AssertionError) else type(error).__name__)
                case['duration_ms'] = round((monotonic() - started) * 1000)
                case['manual_review'] = 'pending' if definition['case_id'].startswith('A') and case['status'] == 'passed' else 'not_applicable'
                cases.append(case)
                print(json.dumps({k: case[k] for k in ('case_id', 'status', 'duration_ms')}, ensure_ascii=False), flush=True)
    finally:
        await db.close_pool()
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=PROJECT_ROOT, capture_output=True, text=True)
    return EvalReport(checked_at=datetime.now(timezone.utc), git_commit=commit.stdout.strip() if commit.returncode == 0 else None, environment={'python': platform.python_version(), 'chat_model': settings.chat_model, 'embedding_model': settings.embedding_model, 'embedding_dimension': str(settings.embedding_dimension), 'data_mode': 'synthetic_postgresql_mock_commerce', 'method': 'program assertions; separate semantic review required; no wording equality; no automatic retry'}, case_count=len(cases), passed=sum(c['status'] == 'passed' for c in cases), failed=sum(c['status'] == 'failed' for c in cases), not_run=sum(c['status'] == 'not_run' for c in cases), cases=cases)


def write_report(report: EvalReport, path: Path) -> None:
    """时间戳文件保留历史，latest只是便于读取的副本。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = report.model_dump_json(indent=2) + '\n'
    stamp = report.checked_at.strftime('%Y%m%dT%H%M%S%fZ')
    with path.with_name(f'{path.stem}-{stamp}{path.suffix}').open('x', encoding='utf-8') as file:
        file.write(content)
    if path.exists():
        previous = path.read_bytes()
        path.with_name(f'{path.stem}-previous-{stamp}{path.suffix}').write_bytes(previous)
        baseline = EvalReport.model_validate({key: value for key, value in json.loads(previous).items() if key in EvalReport.model_fields})
        if baseline.case_count == 20 and report.case_count < 20:
            replacements = {case['case_id']: {**case, 'rerun_checked_at': report.checked_at.isoformat()} for case in report.cases}
            baseline.cases = [replacements.get(case['case_id'], case) for case in baseline.cases]
            baseline.checked_at = report.checked_at
            for status in ('passed', 'failed', 'not_run'):
                setattr(baseline, status, sum(case['status'] == status for case in baseline.cases))
            content = baseline.model_dump_json(indent=2) + '\n'
    path.write_text(content, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='O7 full twenty cases; --cases reruns only affected cases')
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--api-url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    report = asyncio.run(run_evaluation(args.cases, args.api_url), loop_factory=db.create_event_loop)
    write_report(report, PROJECT_ROOT / 'artifacts/eval-report.json')
    print(json.dumps({'case_count': report.case_count, 'passed': report.passed, 'failed': report.failed, 'not_run': report.not_run}))
    raise SystemExit(1 if report.failed or report.not_run else 0)
