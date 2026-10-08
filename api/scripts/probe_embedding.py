"""一次真实 embedding 探测；只成功设置维度，失败安全诊断不泄露请求正文。"""
import argparse
import asyncio
import json
import socket
import ssl
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlsplit
from dotenv import set_key
from app import db
from app.config import PROJECT_ROOT, get_settings
from app.adapters.embedding import probe_embedding


def safe_error_details(error: BaseException) -> dict:
    """只取错误类型和数字码，排除URL、请求头、响应正文、密钥。"""
    pending = [error]
    seen = set()
    chain = []
    while pending and len(chain) < 20:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        chain.append({'type':type(current).__name__, 'errno':getattr(current,'errno',None), 'winerror':getattr(current,'winerror',None), 'http_status':getattr(current,'status_code',None)})
        pending.extend(e for e in [current.__cause__, current.__context__] if e is not None)
        pending.extend(getattr(current,'exceptions',()))
    return {'error_type':type(error).__name__, 'http_status':getattr(error,'status_code',None), 'error_chain':chain}


def save_probe(result: dict) -> None:
    """成功/失败都保存，保留既有探测历史，不把旧成功当本次成功。"""
    settings=get_settings()
    result.update({'checked_at':datetime.now(timezone.utc).isoformat(),'endpoint_fingerprint':sha256(settings.embedding_base_url.encode()).hexdigest()})
    directory=PROJECT_ROOT/'artifacts'
    directory.mkdir(exist_ok=True)
    path=directory/'embedding-probe.json'
    if path.exists():
        previous=json.loads(path.read_text(encoding='utf-8'))
        result['previous_attempts']=previous.get('previous_attempts',[])+[{k:v for k,v in previous.items() if k!='previous_attempts'}]
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


async def main(save_dimension: bool):
    try:
        result=await probe_embedding()
        if save_dimension:
            set_key(str(PROJECT_ROOT/'.env'),'EMBEDDING_DIMENSION',str(result['dimension']))
            get_settings.cache_clear()
        save_probe(result)
        print(json.dumps({k:v for k,v in result.items() if k!='previous_attempts'},ensure_ascii=False))
    except Exception as error:
        result={'status':'failed',**safe_error_details(error),'detail':'未收到有效向量，未设置维度；连接错误不代表密钥/模型无效'}
        save_probe(result)
        print(json.dumps({k:v for k,v in result.items() if k!='previous_attempts'},ensure_ascii=False))
        raise SystemExit(1) from None


def diagnose_network() -> None:
    """对同一配置主机做DNS/TCP/TLS只读诊断，不发送密钥或模型请求。"""
    target=urlsplit(get_settings().embedding_base_url)
    result={'mode':'network_only_no_credentials','host':target.hostname,'port':target.port or (443 if target.scheme=='https' else 80),'dns':'not_run','tcp':'not_run','tls':'not_run'}
    if not target.hostname:
        print(json.dumps({**result,'status':'failed','detail':'EMBEDDING_BASE_URL不是带主机的有效URL'},ensure_ascii=False))
        return
    try:
        addresses=socket.getaddrinfo(target.hostname,result['port'],type=socket.SOCK_STREAM)
        result.update({'dns':'passed','resolved_address_count':len(addresses)})
        with socket.create_connection((target.hostname,result['port']),timeout=8) as connection:
            result['tcp']='passed'
            if target.scheme=='https':
                with ssl.create_default_context().wrap_socket(connection,server_hostname=target.hostname):
                    result['tls']='passed'
        result['status']='passed'
    except Exception as error:
        result.update({'status':'failed',**safe_error_details(error)})
    (PROJECT_ROOT/'artifacts').mkdir(exist_ok=True)
    (PROJECT_ROOT/'artifacts/embedding-network-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--set-dimension',action='store_true')
    parser.add_argument('--diagnose',action='store_true',help='仅DNS/TCP/TLS，不发embedding请求，不带密钥')
    args=parser.parse_args()
    if args.diagnose:
        diagnose_network()
    else:
        asyncio.run(main(args.set_dimension),loop_factory=db.create_event_loop)
