"""独立 embedding 接口；不生成替代向量。"""
import math
from typing import Any
from urllib.parse import urlsplit
import httpx
from openai import AsyncOpenAI
from app.config import get_settings
from app.schemas import DomainError

class EmbeddingAdapter:
    """一次真实向量请求，模型与聊天独立配置。"""
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """生成真实向量并校验数量、维度和有限数值。"""
        settings = get_settings()
        local = urlsplit(settings.embedding_base_url).hostname in {'127.0.0.1', 'localhost', '::1'}
        key = settings.embedding_api_key.get_secret_value() or ('local-no-secret' if local else '')
        if not all((settings.embedding_base_url, settings.embedding_model, key)):
            raise DomainError('KNOWLEDGE_UNAVAILABLE', '请在本地 .env 填写 EMBEDDING_BASE_URL、EMBEDDING_API_KEY、EMBEDDING_MODEL', 503)
        # 只对本地向量服务关闭环境代理；聊天客户端不受影响。
        async with AsyncOpenAI(base_url=settings.embedding_base_url, api_key=key, timeout=30, max_retries=0,
                              http_client=httpx.AsyncClient(trust_env=not local)) as client:
            response = await client.embeddings.create(model=settings.embedding_model, input=texts, encoding_format='float')
        if sorted(item.index for item in response.data) != list(range(len(texts))):
            raise DomainError('EMBEDDING_INVALID_RESPONSE','embedding 返回 index 缺失或重复',502)
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        if len(vectors) != len(texts) or not vectors or not vectors[0] or any(len(vector) != len(vectors[0]) or not all(math.isfinite(x) for x in vector) or not any(x != 0 for x in vector) for vector in vectors):
            raise DomainError('EMBEDDING_INVALID_RESPONSE','embedding 返回数量、数值或维度无效',502)
        if settings.embedding_dimension and len(vectors[0]) != settings.embedding_dimension:
            raise DomainError('EMBEDDING_DIMENSION_MISMATCH','实际维度与 EMBEDDING_DIMENSION 不一致',503)
        return vectors

async def probe_embedding() -> dict[str, Any]:
    """一次真实向量探测，返回实际维度，不泄露密钥。"""
    vectors = await EmbeddingAdapter().embed_texts(['选购助手的演示退换政策', '商品保修演示说明'])
    return {'status': 'passed', 'model': get_settings().embedding_model, 'dimension': len(vectors[0]), 'vector_count': len(vectors), 'finite_values': True, 'nonzero_vectors': True}
