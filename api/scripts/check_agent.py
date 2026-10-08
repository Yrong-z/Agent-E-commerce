"""O3 有限阶段检查；离线与在线分开，只运行配置齐全的聊天探测/场景。"""
import argparse
import asyncio
import json
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
from uuid import uuid4
import httpx
from app import db
from app.config import PROJECT_ROOT,get_settings
from app.adapters.model import probe_tool_calling
from app.schemas import DomainError

SCENARIOS=['两款有货通勤耳机','第二款详情','降噪比较','降预算保留用途','缺订单号追问并继续物流','工具失败与显式重试']

async def main(api_url: str):
    """保存实际请求/原生配对证据，无配置不运行在线场景。"""
    path=PROJECT_ROOT/'artifacts/agent-check.json'
    report=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    previous_probe=report.get('tool_calling_probe')
    if previous_probe:
        report.setdefault('previous_probe_attempts',[]).append({'checked_at':report.get('checked_at'),**previous_probe})
    report.update({'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'O3_only_with_O2_regression','excluded':['after-sales','RAG','MCP','full-project acceptance']})
    settings=get_settings()
    missing=[name for name,value in [('CHAT_BASE_URL',settings.chat_base_url),('CHAT_API_KEY',settings.chat_api_key.get_secret_value()),('CHAT_MODEL',settings.chat_model)] if not value]
    report['chat_configuration']={'missing_variables':missing,'embedding_required':False}
    xml_path=PROJECT_ROOT/'artifacts/agent-tests.xml'
    if xml_path.exists():
        suite=ET.parse(xml_path).getroot().find('testsuite')
        report['deterministic_tests']={'mode':'offline_model_fixtures_and_real_database','status':'passed' if int(suite.attrib['failures'])+int(suite.attrib['errors'])==0 else 'failed',**{key:int(suite.attrib[key]) for key in ['tests','failures','errors','skipped']}}
    else: report['deterministic_tests']={'mode':'offline','status':'not_run'}
    cases=[]
    report['online_cases']=cases
    async with httpx.AsyncClient(base_url=api_url,timeout=65) as client:
        async def online_turn(message,session_id=None):
            response=await client.post('/api/chat',json={'session_id':session_id,'message':message,'client_message_id':str(uuid4())})
            assert response.status_code==200
            result=response.json()
            trace=(await client.get('/api/traces/'+result['request_id'])).json()
            restored=(await client.get('/api/sessions/'+result['session_id'])).json()
            native=[]
            for item in restored['state']['recent_messages']:
                if item.get('tool_calls'):
                    native.append({'role':'assistant','calls':[{'id':call['id'],'name':call['function']['name'],'arguments':call['function']['arguments']} for call in item['tool_calls']]})
                elif item['role']=='tool': native.append({'role':'tool','tool_call_id':item['tool_call_id'],'result':json.loads(item['content'])})
            return result,{'request':message,'response':result,'traces':trace,'native_protocol_evidence':native}
        # 无付费模型依赖的真实接口检查；仅清理本次创建的临时会话与 traces。
        temporary_session=None; temporary_request=None
        try:
            assert (await client.get('/api/sessions')).status_code==200
            assert (await client.get('/api/sessions/nonexistent-o3-check')).status_code==404
            assert (await client.get('/api/traces/nonexistent-o3-check')).status_code==404
            if missing:
                body={'message':'O3 配置缺失验证','client_message_id':str(uuid4())}
                first=await client.post('/api/chat',json=body); assert first.status_code==200
                result=first.json(); temporary_session=result['session_id']; temporary_request=result['request_id']
                assert result['status']=='failed' and result['error']['code']=='MODEL_NOT_CONFIGURED' and not result['view_state']['products']
                duplicate=await client.post('/api/chat',json={**body,'session_id':temporary_session})
                assert duplicate.json()==result
                restored=await client.get('/api/sessions/'+temporary_session)
                assert restored.status_code==200 and restored.json()['state']['display_messages'][1]['status']=='failed'
                trace=await client.get('/api/traces/'+temporary_request)
                assert trace.status_code==200 and any(e['error']=='MODEL_NOT_CONFIGURED' for e in trace.json())
            report['implemented_http']={'status':'passed','mode':'live_local_api','session_list_and_restore':200,'missing_session_and_trace':404,'unconfigured_chat_and_dedup':'passed' if missing else 'not_run'}
        except Exception as error:
            report['implemented_http']={'status':'failed','mode':'live_local_api','error':type(error).__name__}
        finally:
            if temporary_session:
                await db.open_pool()
                try:
                    async with db.get_connection() as connection:
                        await connection.execute('DELETE FROM sessions WHERE session_id=%s AND customer_id=%s',(temporary_session,settings.demo_customer_id))
                        await connection.execute('DELETE FROM traces WHERE request_id=%s',(temporary_request,))
                finally: await db.close_pool()
        if missing:
            report['tool_calling_probe']={'status':'not_run','mode':'online','detail':'聊天配置缺失；embedding 不是阻塞条件'}
            cases.extend({'name':name,'mode':'online','status':'not_run','reason':'聊天配置缺失'} for name in SCENARIOS)
        else:
            try:
                report['tool_calling_probe']={**await probe_tool_calling(),'mode':'online'}
            except Exception as error:
                report['tool_calling_probe']={'status':'failed','mode':'online','code':error.code if isinstance(error,DomainError) else type(error).__name__,'detail':error.message if isinstance(error,DomainError) else '未获得合法原生工具调用；不更换模型'}
            if report['tool_calling_probe']['status']!='passed':
                cases.extend({'name':name,'mode':'online','status':'not_run','reason':'原生工具兼容性探测失败'} for name in SCENARIOS)
            else:
                session_id=None
                messages=['300 元内推荐两款有货通勤耳机','第二款详情','对比这两款，关注降噪','把预算改为 200 元','查询我的已有订单物流','查询订单 NOT-FOUND-O3 的物流，不要替换其他订单']
                for index,(name,message) in enumerate(zip(SCENARIOS,messages)):
                    evidence=[]
                    try:
                        result,item=await online_turn(message,session_id); session_id=result['session_id']; evidence.append(item)
                        view=result['view_state']
                        if index==0:
                            assert result['status']=='completed' and [p['product_id'] for p in view['products']]==['DEMO-A1','DEMO-B2']
                            assert view['constraints']['budget_max_fen']==30000 and view['constraints']['use_case']=='通勤' and view['constraints']['in_stock_only']
                        elif index==1:
                            assert result['status']=='completed' and view['focused_product']['product_id']=='DEMO-B2' and [p['product_id'] for p in view['products']]==['DEMO-A1','DEMO-B2']
                        elif index==2:
                            assert result['status']=='completed' and view['comparison']['product_ids']==['DEMO-A1','DEMO-B2']
                            assert next(r for r in view['comparison']['rows'] if r['field']=='anc')['values']==[False,True]
                        elif index==3:
                            assert result['status']=='completed' and [p['product_id'] for p in view['products']]==['DEMO-A1'] and view['constraints']['use_case']=='通勤' and view['constraints']['in_stock_only']
                        elif index==4:
                            assert result['status']=='needs_input' and view['order'] is None
                            result,item=await online_turn('DEMO20261003001',session_id); evidence.append(item)
                            assert result['status']=='completed' and result['view_state']['order']['order_id']=='DEMO20261003001' and result['view_state']['order']['logistics']['summary']=='快件已到达配送站'
                        else:
                            assert result['status']=='failed' and result['error']['code']=='ORDER_NOT_FOUND'
                            result,item=await online_turn('重新查询订单 DEMO20261003001 的物流',session_id); evidence.append(item)
                            assert result['status']=='completed' and result['view_state']['order']['order_id']=='DEMO20261003001'
                        assert any(any(event['tool_name'] not in ('model','agent') for event in e['traces']) for e in evidence)
                        cases.append({'name':name,'mode':'online','status':'passed','evidence':evidence})
                    except Exception as error:
                        cases.append({'name':name,'mode':'online','status':'failed','error':type(error).__name__,'evidence':evidence})
    report['online_summary']={status:sum(c['status']==status for c in cases) for status in ['passed','failed','not_run']}
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ['scope','chat_configuration','deterministic_tests','implemented_http','tool_calling_probe','online_summary']},ensure_ascii=False,indent=2))
    if report['implemented_http']['status']=='failed' or report['tool_calling_probe']['status']=='failed' or report['online_summary']['failed']:
        raise SystemExit(1)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='O3 有限聊天验收，不要求 embedding，不运行 O4–O7')
    parser.add_argument('--api-url',default='http://127.0.0.1:8000')
    asyncio.run(main(parser.parse_args().api_url),loop_factory=db.create_event_loop)
