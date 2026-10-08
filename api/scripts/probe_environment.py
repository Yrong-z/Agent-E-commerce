"""一次模型与向量预检；缺配置记录 not_run，禁止假成功。"""
import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit
from app.config import PROJECT_ROOT, get_settings
from app.adapters.model import probe_tool_calling
from app.adapters.embedding import probe_embedding

async def main() -> None:
    """只执行配置完整的探测；保存脱敏实际结果。"""
    settings = get_settings()
    report = {'checked_at': datetime.now(timezone.utc).isoformat()}
    for name, ready, probe in [
        ('tool_calling', bool(settings.chat_base_url and settings.chat_model and settings.chat_api_key.get_secret_value()), probe_tool_calling),
        ('embedding', bool(settings.embedding_base_url and settings.embedding_model and (settings.embedding_api_key.get_secret_value() or urlsplit(settings.embedding_base_url).hostname in {'127.0.0.1', 'localhost', '::1'})), probe_embedding),
    ]:
        if not ready:
            report[name] = {'status': 'not_run', 'detail': '本地模型配置不完整'}
        else:
            try:
                report[name] = await probe()
            except Exception as error:
                report[name] = {'status': 'failed', 'detail': type(error).__name__}  # 不保存外部异常文本
    path = PROJECT_ROOT / 'artifacts' / 'model-probes.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))

if __name__ == '__main__':
    asyncio.run(main())
