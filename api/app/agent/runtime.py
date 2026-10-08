"""有限原生模型工具循环；四次模型、八次工具、整体最多六十秒。"""
import asyncio
import json
from time import monotonic
from uuid import uuid4
from app.config import get_settings
from app.schemas import ChatRequest, ChatResponse, SessionState, ToolResult, ViewState, ApiError, TraceEvent, DomainError
from app.agent.tools import LocalToolExecutor, build_tool_definitions, TOOL_ARGUMENT_MODELS
from app.agent.prompts import build_model_messages
from app.agent.state import append_history_turn
from app.adapters.model import ChatModelAdapter
from app.services.trace import record_trace_event

MAX_MODEL_CALLS = 4
MAX_TOOL_EXECUTIONS = 8
REQUEST_TIMEOUT_SECONDS = 60

def build_view_state(results: list[ToolResult], session: SessionState) -> ViewState:
    """完整快照仅由已执行的工具维护，正文不参与事实字段生成。"""
    view = session.view_state.model_copy(deep=True)
    for result in results:
        if result.view_updates is not None:
            view = result.view_updates.model_copy(deep=True)
    view.constraints = session.constraints.model_copy(deep=True)
    view.active_task = session.active_task
    return view

def _arguments_summary(name: str, args: dict) -> str:
    """仅摘要允许参数；文本查询只记长度，未知工具不存原始参数。"""
    model = TOOL_ARGUMENT_MODELS.get(name)
    if model is None:
        return '未注册工具；参数不记录'
    values = {}
    for key,value in args.items():
        if key not in model.model_fields:
            continue
        values[key] = {'text_length':len(value)} if key=='query' and isinstance(value,str) else value
    return json.dumps(values,ensure_ascii=False)[:300]

async def run_agent_turn(request: ChatRequest, session: SessionState, request_id: str | None = None, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> ChatResponse:
    """不解析普通文本为调用；所有 native tool_call_id 配对完整才保存历史。"""
    request_id = request_id or str(uuid4())
    deadline = monotonic()+max(0,timeout_seconds)
    session.view_state.citations = []  # 本轮引用仅由本轮真实检索生成。
    messages = build_model_messages(session,request.message)
    turn = [{'role':'user','content':request.message}]
    results = []
    tool_count = 0
    failure = None
    answer = ''
    settings = get_settings()
    async def trace(name,arguments,result,duration,error=None):
        await record_trace_event(TraceEvent(request_id=request_id,tool_name=name,arguments_summary=arguments,result_summary=result,duration_ms=max(0,int(duration*1000)),error=error,sources=session.view_state.citations if name=='search_knowledge' and not error else []))
    def error_result(code,message):
        return ToolResult(ok=False,error=ApiError(code=code,message=message,retryable=code in {'MODEL_TIMEOUT','TOOL_TIMEOUT','TOOL_FAILED','MODEL_FAILED','MODEL_HTTP_ERROR','MODEL_CONNECTION_FAILED','AGENT_FAILED','MODEL_PROTOCOL_ERROR'},request_id=request_id),view_updates=session.view_state.model_copy(deep=True))
    try:
        if not all((settings.chat_base_url,settings.chat_api_key.get_secret_value(),settings.chat_model)):
            failure = ApiError(code='MODEL_NOT_CONFIGURED',message='聊天模型未配置；请在本地填写 CHAT_BASE_URL、CHAT_API_KEY、CHAT_MODEL',request_id=request_id)
            await trace('model','配置完整性检查','未调用在线模型',0,failure.code)
        else:
            for model_index in range(MAX_MODEL_CALLS):
                started = monotonic()
                try:
                    async with asyncio.timeout(max(0,deadline-monotonic())):
                        response = await ChatModelAdapter().complete_with_tools(messages,build_tool_definitions())
                    if not response.choices:
                        raise DomainError('MODEL_PROTOCOL_ERROR','模型返回缺少有效消息',502)
                    message = response.choices[0].message
                    calls = message.tool_calls or []
                    await trace('model',f'调用 {model_index+1}/{MAX_MODEL_CALLS}',f'原生工具调用 {len(calls)} 个' if calls else '返回最终解释',monotonic()-started)
                except TimeoutError:
                    failure = error_result('MODEL_TIMEOUT','聊天请求超时，本次未完成，请重试').error
                    await trace('model','模型请求','未完成',monotonic()-started,failure.code)
                    break
                except DomainError as error:
                    failure = error_result(error.code,error.message).error
                    await trace('model','模型请求','未完成',monotonic()-started,failure.code)
                    break
                if not calls:
                    if not message.content or not message.content.strip() or response.choices[0].finish_reason not in ('stop',None):
                        failure = error_result('MODEL_PROTOCOL_ERROR','模型未返回完整解释，本次未完成').error
                        break
                    answer = message.content
                    turn.append({'role':'assistant','content':answer})
                    break
                ids = [call.id for call in calls]
                if any(not call.id or call.type!='function' for call in calls) or len(set(ids))!=len(ids):
                    failure = error_result('MODEL_PROTOCOL_ERROR','原生工具调用 ID 或类型无效').error
                    break
                assistant = {'role':'assistant','content':message.content,'tool_calls':[{'id':call.id,'type':'function','function':{'name':call.function.name,'arguments':call.function.arguments}} for call in calls]}
                block = [assistant]
                # 整个工具批次的每个 ID 都回传，即使预算或参数失败；不保存半组历史。
                for call in calls:
                    started = monotonic()
                    args = {}
                    try:
                        args = json.loads(call.function.arguments)
                        if not isinstance(args,dict):
                            raise ValueError
                        if tool_count>=MAX_TOOL_EXECUTIONS:
                            result = error_result('TOOL_LIMIT','达到八次工具执行上限，本次未完成')
                        elif monotonic()>=deadline:
                            result = error_result('TOOL_TIMEOUT','请求时间已耗尽，本次未完成')
                        else:
                            tool_count += 1
                            async with asyncio.timeout(max(0,deadline-monotonic())):
                                result = await LocalToolExecutor().execute(call.function.name,args,session)
                            if result.error:
                                result.error.request_id = request_id
                    except (ValueError,TypeError):
                        args = {}
                        result = error_result('INVALID_ARGUMENT','工具参数不是合法 JSON 对象')
                    except TimeoutError:
                        result = error_result('TOOL_TIMEOUT','工具执行超时，本次未完成，请重试')
                    results.append(result)
                    block.append({'role':'tool','tool_call_id':call.id,'content':result.model_dump_json(exclude={'view_updates'})})
                    summary = '成功：'+(f'列表 {len(result.data)} 项' if isinstance(result.data,list) else '已读取业务事实') if result.ok else '未完成'
                    await trace(call.function.name,_arguments_summary(call.function.name,args),summary,monotonic()-started,result.error.code if result.error else None)
                    if result.error and result.error.code!='NEEDS_INPUT':
                        failure = result.error
                turn.extend(block)
                messages.extend(block)
                if failure:
                    break
            else:
                failure = error_result('MODEL_CALL_LIMIT','达到四次模型调用上限，本次未完成').error
    except Exception:
        # 外部异常正文可能含凭据；只返回稳定错误，不打印或持久化异常字符串。
        failure = error_result('AGENT_FAILED','会话处理失败，本次未完成，请重试').error
    if failure:
        answer = failure.message
        try:
            await trace('agent','有限会话处理','失败；未宣称成功',0,failure.code)
        except Exception:
            pass  # 数据库故障时无法落库；失败响应仍明确，不输出异常正文。
        # 本地错误不冒充模型回答；展示记录另存，模型历史只保留已配对片段。
    append_history_turn(session,turn)
    from app.agent.state import append_display_turn
    append_display_turn(session, request.message, answer, 'failed' if failure else 'needs_input' if session.pending_question else 'completed')
    if session.title=='新会话':
        session.title = request.message[:40]
    session.view_state = build_view_state(results,session)
    return ChatResponse(request_id=request_id,session_id=session.session_id,answer=answer,status='failed' if failure else 'needs_input' if session.pending_question else 'completed',view_state=session.view_state,error=failure)
