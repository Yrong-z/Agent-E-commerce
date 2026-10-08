"""连接诊断脱敏、真实任务快照与失败重试显示的必要回归；不充当在线证据。"""
from datetime import datetime, timezone
import json
import socket
from openai import APIConnectionError
import httpx
from app.adapters.model import connection_diagnostic
from app.agent.runtime import build_view_state
from app.agent.state import append_display_turn, append_history_turn
from app.agent.prompts import build_model_messages
from app.schemas import SessionState, AfterSalesPreview

def test_connection_diagnostic_does_not_serialize_credentials():
    root = socket.gaierror(11001, 'secret-proxy-user:secret-password request-key')
    transport = httpx.ConnectError('secret-request')
    transport.__cause__ = root
    error = APIConnectionError(request=httpx.Request('POST', 'https://secret-key@example.test'))
    error.__cause__ = transport
    result = connection_diagnostic(error, 'connection.connect_tcp.failed')
    assert [item['type'] for item in result['exceptions']] == ['APIConnectionError','ConnectError','gaierror']
    assert result['exceptions'][-1]['errno'] == 11001
    assert 'secret' not in json.dumps(result)

def test_retry_updates_failed_turn_and_preserves_task_history():
    session = SessionState(session_id='offline-regression',updated_at=datetime.now(timezone.utc))
    append_history_turn(session, [{'role':'user','content':'change budget'}])
    append_display_turn(session, 'change budget', 'connection failed', 'failed')
    assert len([item for item in build_model_messages(session,'change budget') if item['role']=='user']) == 1
    append_history_turn(session, [{'role':'user','content':'change budget'}])
    assert len(session.recent_messages) == 1
    append_display_turn(session, 'change budget', 'still failed', 'failed')
    append_display_turn(session, 'change budget', 'recovered', 'completed')
    assert session.display_messages == [{'role':'user','content':'change budget'}, {'role':'assistant','content':'recovered','status':'completed'}]
    append_display_turn(session, 'change budget', 'new turn', 'completed')
    assert len(session.display_messages) == 4  # 正常重复输入仍是新一轮。
    session.active_task = 'after_sales'
    assert build_view_state([],session).active_task == 'after_sales'
    session.active_task = 'shopping'
    assert build_view_state([],session).active_task == 'shopping'

def test_prompt_uses_current_application_status_instead_of_history():
    session = SessionState(session_id='offline-status',updated_at=datetime.now(timezone.utc))
    session.view_state.after_sales_preview = AfterSalesPreview(
        preview_id='preview-test',order_id='order-test',reason='reason-test',status='submitted',
        eligible=True,explanation='saved',refund_amount_fen=19900,policy_source_ids=[],policy_sources=[],
        expires_at=datetime.now(timezone.utc),application_id='application-test')
    context = json.loads(build_model_messages(session,'budget')[0]['content'].split('\n当前业务状态：')[-1])
    assert context['after_sales_status']['status'] == 'submitted'
    assert context['after_sales_status']['application_id'] == 'application-test'
    assert context['after_sales_status']['expires_at'] is None
