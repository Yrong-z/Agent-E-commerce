"""真实官方 SDK stdio 客户端有限验收；原始报告和 stderr 仅保存在本地。"""
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from importlib.metadata import version

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from app.config import PROJECT_ROOT


class ProtocolErrors(logging.Handler):
    """只统计协议解析错误，不公开消息正文。"""
    def __init__(self):
        super().__init__()
        self.count = 0

    def emit(self, record):
        if 'Failed to parse JSONRPC' in record.getMessage():
            self.count += 1


async def check_mcp_tools() -> dict:
    """完成 initialize/list_tools/call_tool，关闭 stdin 后验证连接池释放。"""
    report = {'scope': 'O6_read_only_stdio', 'checked_at': datetime.now(timezone.utc).isoformat(),
              'sdk_version': version('mcp'), 'transport': 'stdio', 'checks': [], 'unresolved': []}
    checks = report['checks']
    runtime = PROJECT_ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    stderr_path = runtime / 'mcp-check-stderr.log'
    protocol_errors = ProtocolErrors()
    client_logger = logging.getLogger('mcp.client.stdio')
    client_logger.addHandler(protocol_errors)

    def record(name, passed, detail=None):
        checks.append({'name': name, 'mode': 'real_mcp_protocol', 'status': 'passed' if passed else 'failed', 'detail': detail})

    async def connect_and_check(errlog, unavailable=False):
        env = {'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8'}
        if unavailable:
            # 独立子进程的故障配置，不停止实际数据库，不修改本地配置。
            env['DATABASE_URL'] = 'postgresql://unused:unused@127.0.0.1:1/unused'
        parameters = StdioServerParameters(command=sys.executable, args=['-m', 'app.mcp_server'], env=env, cwd=PROJECT_ROOT)
        async with stdio_client(parameters, errlog=errlog) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=20)) as client:
                initialized = await client.initialize()
                if unavailable:
                    result = await client.call_tool('get_order', {'order_id': 'DEMO20261003002'})
                    record('dependency_unavailable', result.isError and 'DEPENDENCY_UNAVAILABLE' in result.model_dump_json())
                    return
                record('initialize', bool(initialized.protocolVersion), {'protocol_version': initialized.protocolVersion})
                listed = await client.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                schema = tools.get('search_products').inputSchema if 'search_products' in tools else {}
                record('list_two_read_only_tools_and_schema', set(tools) == {'search_products', 'get_order'}
                       and all(t.annotations and t.annotations.readOnlyHint for t in tools.values())
                       and schema.get('properties', {}).get('limit', {}).get('maximum') == 6
                       and tools['get_order'].inputSchema.get('required') == ['order_id'],
                       {'tools': sorted(tools), 'input_schemas': {name: tool.inputSchema for name, tool in tools.items()}})
                result = await client.call_tool('search_products', {'budget_max_fen': 30000, 'use_case': '通勤', 'in_stock_only': True, 'limit': 2})
                products = (result.structuredContent or {}).get('result', [])
                record('search_real_database_products', not result.isError and [p['product_id'] for p in products] == ['DEMO-A1', 'DEMO-B2'],
                       {'products': [{'product_id': p['product_id'], 'sale_price_fen': p['sale_price_fen']} for p in products]})
                result = await client.call_tool('get_order', {'order_id': 'DEMO20261003002'})
                order = result.structuredContent or {}
                record('get_real_owned_order_historical_amount', not result.isError and order.get('order_id') == 'DEMO20261003002'
                       and order.get('paid_total_fen') == 27900, {'order_id': order.get('order_id'), 'paid_total_fen': order.get('paid_total_fen')})
                result = await client.call_tool('search_products', {'budget_max_fen': 100, 'use_case': '通勤'})
                record('empty_result', not result.isError and result.structuredContent == {'result': []})
                result = await client.call_tool('get_order', {'order_id': 'NOT-FOUND-MCP'})
                record('unknown_order', result.isError and 'ORDER_NOT_FOUND' in result.model_dump_json())
                invalid = [await client.call_tool('search_products', args) for args in ({'limit': 0}, {'budget_max_fen': -1}, {'limit': '2'})]
                record('invalid_parameters', all(r.isError for r in invalid), {'cases': ['limit_zero', 'negative_budget', 'string_limit']})

    try:
        with stderr_path.open('w', encoding='utf-8') as errlog:
            await connect_and_check(errlog)
            await connect_and_check(errlog, unavailable=True)
        stderr = stderr_path.read_text(encoding='utf-8')
        record('normal_shutdown_pool_closed_stderr_only', stderr.count('MCP database pool opened') == 2
               and stderr.count('MCP database pool closed') == 2 and protocol_errors.count == 0,
               {'pool_opened': stderr.count('MCP database pool opened'), 'pool_closed': stderr.count('MCP database pool closed'),
                'stdout_protocol_parse_errors': protocol_errors.count})
    except Exception as error:
        # 不输出子进程环境、请求正文或异常堆栈；失败同样落盘，不冒充成功。
        record('client_connection_or_execution', False, {'error_type': type(error).__name__})
    finally:
        client_logger.removeHandler(protocol_errors)
    report['status'] = 'passed' if checks and all(c['status'] == 'passed' for c in checks) else 'failed'
    directory = PROJECT_ROOT / 'artifacts'
    directory.mkdir(exist_ok=True)
    path = directory / 'mcp-check.json'
    if path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        report['previous_attempts'] = previous.get('previous_attempts', []) + [{k: v for k, v in previous.items() if k != 'previous_attempts'}]
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    # Windows 客户端使用默认 Proactor 来启动子进程；服务端独立使用 Selector。
    result = asyncio.run(check_mcp_tools())
    print(json.dumps({k: result[k] for k in ('scope', 'status', 'sdk_version', 'checks')}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['status'] == 'passed' else 1)
