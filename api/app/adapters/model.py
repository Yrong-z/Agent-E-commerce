"""Chat Completions 原生 tools 适配及一次真实兼容性探测。"""
import json
import logging
import os
import httpx
from urllib.parse import urlsplit
from typing import Any
from openai import AsyncOpenAI, APIStatusError, APIConnectionError, APITimeoutError
from openai.types.chat import ChatCompletion
from app.config import get_settings, PROJECT_ROOT
from app.schemas import DomainError

logger = logging.getLogger(__name__)

def connection_diagnostic(error: BaseException, stage: str) -> dict[str, Any]:
    """只允许类型/数值与阶段，不序列化异常正文、请求或代理地址。"""
    chain, pending, seen = [], [error], set()
    while pending and len(chain) < 12:
        item = pending.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        numbers = {key: value if isinstance(value, int) else None for key, value in
                   (('errno', getattr(item, 'errno', None)), ('winerror', getattr(item, 'winerror', None)), ('http_status', getattr(item, 'status_code', None)))}
        chain.append({'type': type(item).__name__, **numbers})
        pending.extend(value for value in (item.__cause__, item.__context__, *item.args) if isinstance(value, BaseException))
    return {'stage': stage, 'exceptions': chain}

class ChatModelAdapter:
    """仅负责接口调用；不包含 Agent 循环或业务规则。"""
    _environment_logged = False
    async def complete_with_tools(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: Any = 'auto') -> ChatCompletion:
        """一次原生调用，禁用 SDK 自动重试。"""
        settings = get_settings()
        if not all((settings.chat_base_url, settings.chat_model, settings.chat_api_key.get_secret_value())):
            raise DomainError('MODEL_NOT_CONFIGURED','请在本地 .env 填写 CHAT_BASE_URL、CHAT_API_KEY、CHAT_MODEL',503)
        try:
            stage = 'client_setup'
            async def trace(name, info):
                nonlocal stage
                stage = name  # httpcore 阶段名；不读取 info 中的 URL/headers/异常正文。
            async def attach_trace(request):
                request.extensions['trace'] = trace
            environment = {
                'cwd_is_project_root': os.path.abspath(os.getcwd()) == str(PROJECT_ROOT),
                'proxy_env_present': {name: bool(os.environ.get(name)) for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY')},
                'configuration_env_overrides': {name: bool(os.environ.get(name)) for name in ('CHAT_BASE_URL','CHAT_API_KEY','CHAT_MODEL')},
                'chat_configured': True, 'serve_frontend': settings.serve_frontend,
            }
            if not ChatModelAdapter._environment_logged:
                logger.warning('chat_environment %s', json.dumps(environment))
                ChatModelAdapter._environment_logged = True
            # 官方 DeepSeek 默认思考模式要求回传隐藏推理，且拒绝强制工具。
            # 本项目明确使用同一模型的非思考模式，其他兼容接口不附加此字段。
            options = {'extra_body': {'thinking': {'type': 'disabled'}}} if urlsplit(settings.chat_base_url).hostname == 'api.deepseek.com' else {}
            async with AsyncOpenAI(base_url=settings.chat_base_url, api_key=settings.chat_api_key.get_secret_value(), timeout=30, max_retries=0,
                                  http_client=httpx.AsyncClient(event_hooks={'request':[attach_trace]})) as client:
                return await client.chat.completions.create(model=settings.chat_model, messages=messages, tools=tools, tool_choice=tool_choice, **options)
        except APITimeoutError as error:
            logger.warning('chat_connection_diagnostic %s', json.dumps(connection_diagnostic(error, stage)))
            raise DomainError('MODEL_TIMEOUT','模型接口超时，请重试',504) from None
        except APIStatusError as error:
            logger.warning('chat_connection_diagnostic %s', json.dumps(connection_diagnostic(error, stage)))
            raise DomainError('MODEL_HTTP_ERROR',f'模型接口返回 HTTP {error.status_code}；请检查鉴权、模型名称与原生 tools 支持',502) from None
        except APIConnectionError as error:
            logger.warning('chat_connection_diagnostic %s', json.dumps(connection_diagnostic(error, stage)))
            raise DomainError('MODEL_CONNECTION_FAILED','无法连接聊天模型接口，请检查本地地址与网络',502) from None

async def probe_tool_calling() -> dict[str, Any]:
    """使用独立探测工具检查原生 tool_calls，不注册业务占位工具。"""
    tool = {'type': 'function', 'function': {'name': 'probe_echo', 'description': '兼容性探测：原样传回文字', 'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text'], 'additionalProperties': False}}}
    response = await ChatModelAdapter().complete_with_tools([{'role': 'user', 'content': '调用 probe_echo，text 为 shopping-probe'}], [tool], {'type': 'function', 'function': {'name': 'probe_echo'}})
    calls = response.choices[0].message.tool_calls or []
    if len(calls)!=1 or not calls[0].id or calls[0].type!='function' or calls[0].function.name != 'probe_echo' or json.loads(calls[0].function.arguments) != {'text':'shopping-probe'}:
        raise RuntimeError('未获得符合协议的原生工具调用')
    return {'status': 'passed', 'model': get_settings().chat_model, 'tool': 'probe_echo', 'tool_call_count': len(calls)}
