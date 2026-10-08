"""O4 有限实际检查；保留独立报告，不覆盖O3历史，不使用假向量。"""
import asyncio
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from uuid import uuid4
from hashlib import sha256
from urllib.parse import urlsplit
import httpx
from dotenv import set_key
from app import db
from app.config import PROJECT_ROOT, get_settings
from app.adapters.embedding import probe_embedding
from app.services.knowledge import ingest_documents, search_knowledge, list_sources
from app.services.policies import POLICY_FILES, POLICY_DIR

async def main():
    report={'scope':'O4_only','checked_at':datetime.now(timezone.utc).isoformat(),'checks':[], 'excluded':['MCP','full-project acceptance']}
    previous=PROJECT_ROOT/'artifacts/after-sales-rag-check.json'
    if previous.exists():
        history=json.loads(previous.read_text(encoding='utf-8'))
        report['previous_attempts']=history.get('previous_attempts',[])+[{'checked_at':history.get('checked_at'),'checks':history['checks']}]
    checks=report['checks']
    partial=[]
    async def record(name,mode,operation):
        try:
            detail=await operation()
            checks.append({'name':name,'mode':mode,'status':'passed','detail':detail})
            print(name+': passed',flush=True)
            return detail
        except Exception as error:
            checks.append({'name':name,'mode':mode,'status':'failed','error':getattr(error,'code',type(error).__name__),'http_status':getattr(error,'status_code',None),'partial_evidence':list(partial)})
            print(name+': failed',flush=True)
    path=PROJECT_ROOT/'artifacts/after-sales-tests.xml'
    if path.exists():
        suite=ET.parse(path).getroot().find('testsuite')
        checks.append({'name':'deterministic_rules_and_O2_O3_regression','mode':'offline_fixtures_and_real_database','status':'passed' if int(suite.attrib['failures'])+int(suite.attrib['errors'])==0 else 'failed','detail':{k:int(suite.attrib[k]) for k in ['tests','failures','errors','skipped']}})
    await db.open_pool()
    try:
        await db.init_schema()
        settings=get_settings()
        local = urlsplit(settings.embedding_base_url).hostname in {'127.0.0.1', 'localhost', '::1'}
        missing=[key for key,value in [('EMBEDDING_BASE_URL',settings.embedding_base_url),('EMBEDDING_API_KEY',settings.embedding_api_key.get_secret_value() or local),('EMBEDDING_MODEL',settings.embedding_model)] if not value]
        report['embedding_configuration']={'missing_variables':missing}
        if not missing:
            async def probe():
                result=await probe_embedding()
                set_key(str(PROJECT_ROOT/'.env'),'EMBEDDING_DIMENSION',str(result['dimension']))
                get_settings.cache_clear()
                return result
            saved_path=PROJECT_ROOT/'artifacts/embedding-probe.json'
            saved=json.loads(saved_path.read_text(encoding='utf-8')) if saved_path.exists() else {}
            if saved.get('status')=='passed' and saved.get('model')==settings.embedding_model and saved.get('dimension')==settings.embedding_dimension and saved.get('endpoint_fingerprint')==sha256(settings.embedding_base_url.encode()).hexdigest():
                probed=saved
                checks.append({'name':'embedding_probe','mode':'online','status':'passed','detail':saved,'evidence':'本地probe_embedding实际记录；同配置不重复探测'})
            else:
                probed=await record('embedding_probe','online',probe)
        else:
            probed=None
            checks.append({'name':'embedding_probe','mode':'online','status':'not_run','reason':'缺本地embedding配置'})
        if probed:
            async def ingest():
                async def retained_data():
                    async with db.get_connection() as connection:
                        snapshot = {}
                        for table in ('products', 'orders', 'sessions', 'after_sales'):
                            cursor = await connection.execute(f'SELECT count(*),md5(coalesce(string_agg(payload::text,\'\' ORDER BY payload::text),\'\')) FROM {table}' if table != 'sessions' else "SELECT count(*),md5(coalesce(string_agg(state::text,'' ORDER BY state::text),'')) FROM sessions")
                            snapshot[table] = await cursor.fetchone()
                        cursor = await connection.execute("SELECT chunk_id,excerpt FROM knowledge_chunks WHERE source_owner IS DISTINCT FROM 'shopping-assistant-policy-v1' ORDER BY chunk_id")
                        snapshot['other_knowledge'] = await cursor.fetchall()
                        return snapshot
                retained = await retained_data()
                paths=[POLICY_DIR/name for name in POLICY_FILES.values()]
                first=await ingest_documents(paths)
                async with db.get_connection() as connection:
                    cursor=await connection.execute("SELECT chunk_id,excerpt FROM knowledge_chunks WHERE source_owner='shopping-assistant-policy-v1' ORDER BY chunk_id")
                    before=await cursor.fetchall()
                second=await ingest_documents(paths)
                async with db.get_connection() as connection:
                    cursor=await connection.execute("SELECT chunk_id,excerpt FROM knowledge_chunks WHERE source_owner='shopping-assistant-policy-v1' ORDER BY chunk_id")
                    assert before==await cursor.fetchall()
                assert first==second and len(second)==3
                assert retained == await retained_data(), '入库改变了其他业务或知识资料'
                return [s.model_dump() for s in second]
            await record('real_ingest_and_repeat','online_embedding_and_real_database',ingest)
            async def retrieval():
                hits=await search_knowledge('签收后多久可以退货，需要什么条件？')
                assert hits and any(h.document_id=='demo-policy-return' for h in hits)
                assert all(h.chunk_id and h.excerpt for h in hits)
                unrelated=await search_knowledge('火星大气中的氩同位素比例是什么？')
                assert not unrelated
                return {'known_hits':[h.model_dump() for h in hits],'unrelated_hits':[]}
            await record('real_retrieval_sources_and_unrelated','online_embedding_and_real_database',retrieval)
        else:
            for name in ['real_ingest_and_repeat','real_retrieval_sources_and_unrelated','online_policy_answers_and_citations']:
                checks.append({'name':name,'mode':'online','status':'not_run','reason':'embedding尚未真实验证，不能用fixture代替'})
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',timeout=65,trust_env=False) as client:
            async def turn(message,id=None):
                response=await client.post('/api/chat',json={'session_id':id,'message':message,'client_message_id':str(uuid4())})
                assert response.status_code==200
                result=response.json()
                trace=(await client.get('/api/traces/'+result['request_id'])).json()
                restored=(await client.get('/api/sessions/'+result['session_id'])).json()
                native=[m for m in restored['state']['recent_messages'] if m.get('tool_calls') or m['role']=='tool']
                return result,{'message':message,'response':result,'trace':trace,'native_messages':native}
            if probed:
                async def policy_online():
                    r,e=await turn('项目演示政策中，签收后的退货期限是什么？请检索资料并给出来源，不申请售后。')
                    assert r['status']=='completed' and r['view_state']['citations'] and not r['view_state']['after_sales_preview']
                    assert any(t['tool_name']=='search_knowledge' and not t['error'] for t in e['trace'])
                    r2,e2=await turn('项目政策是否保证原运费全额退还，以及实际寄回运费由谁承担？请检索，不做无依据保证。',r['session_id'])
                    assert r2['status']=='completed' and any(word in r2['answer'] for word in ['无法确认','未保存','未接入','不能确认'])
                    r3,e3=await turn('请检索项目政策：火星大气中的氩同位素比例是什么？资料不足请明确无法确认。',r['session_id'])
                    assert r3['status']=='completed' and not r3['view_state']['citations'] and any(word in r3['answer'] for word in ['无法确认','未覆盖','没有相关'])
                    assert any(t['tool_name']=='search_knowledge' and not t['error'] for t in e3['trace'])
                    return [e,e2,e3]
                await record('online_policy_answers_and_citations','online_chat_and_embedding',policy_online)
            elif settings.chat_model:
                async def unavailable():
                    r,e=await turn('请检索项目演示政策，签收后退货有什么条件？不要创建售后申请。')
                    assert r['status']=='failed' and r['error']['code'] in ['KNOWLEDGE_UNAVAILABLE','EMBEDDING_FAILED'] and not r['view_state']['citations']
                    assert any(t['tool_name']=='search_knowledge' and t['error'] for t in e['trace'])
                    return e
                await record('online_knowledge_unavailable_no_fake_success','online_chat_with_missing_embedding',unavailable)
            async def after_sales_online():
                evidence=partial
                evidence.clear()
                r,e=await turn('我要申请签收后退货售后。');evidence.append(e)
                assert r['status']=='needs_input'
                id=r['session_id']
                r,e=await turn('订单号 DEMO20261003002',id);evidence.append(e)
                assert r['status']=='needs_input'
                r,e=await turn('原因：佩戴不合适',id);evidence.append(e)
                assert r['status']=='completed' and r['view_state']['after_sales_preview']['status']=='pending'
                preview=r['view_state']['after_sales_preview']; assert preview['refund_amount_fen']==27900 and not preview['application_id']
                assert any(t['tool_name']=='prepare_after_sales' and not t['error'] for t in e['trace'])
                r,e=await turn('先切换导购，推荐200元内有货通勤耳机',id);evidence.append(e)
                assert r['view_state']['constraints']['budget_max_fen']==20000 and r['view_state']['after_sales_preview']['preview_id']==preview['preview_id']
                r,e=await turn('继续刚才售后，我确认',id);evidence.append(e)
                assert r['status']=='completed' and r['view_state']['after_sales_preview']['preview_id']==preview['preview_id'] and not r['view_state']['after_sales_preview']['application_id']
                assert any(t['tool_name']=='get_after_sales' and not t['error'] for t in e['trace'])
                first,second=await asyncio.gather(*[client.post('/api/after-sales/'+preview['preview_id']+'/confirm',json={'session_id':id}) for _ in range(2)])
                assert first.status_code==second.status_code==200 and first.json()['application_id']==second.json()['application_id']
                restored=(await client.get('/api/sessions/'+id)).json()
                assert restored['view_state']['after_sales_preview']['status']=='submitted' and restored['view_state']['constraints']['budget_max_fen']==20000
                return {'turns':evidence,'explicit_interface_confirm':first.json(),'repeated_confirm_same_id':True,'restored_state':restored['view_state']}
            if settings.chat_model:await record('online_after_sales_continuous_and_explicit_confirm','online_chat_and_real_database',after_sales_online)
            else:checks.append({'name':'online_after_sales_continuous_and_explicit_confirm','mode':'online','status':'not_run','reason':'聊天配置缺失'})
    finally:await db.close_pool()
    report['summary']={status:sum(c['status']==status for c in checks) for status in ['passed','failed','not_run']}
    report['o4_all_passed']=all(c['status']=='passed' for c in checks)
    (PROJECT_ROOT/'artifacts/after-sales-rag-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],ensure_ascii=False))
    if report['summary']['failed']:raise SystemExit(1)

if __name__=='__main__':asyncio.run(main(),loop_factory=db.create_event_loop)
