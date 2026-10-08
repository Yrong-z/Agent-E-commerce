"""少量白名单政策的真实 embedding、原子替换与 pgvector 检索。"""
import json
from pathlib import Path
from hashlib import sha256
from app import db
from app.config import get_settings
from app.adapters.embedding import EmbeddingAdapter
from app.schemas import KnowledgeHit, KnowledgeSource, DomainError
from app.services.policies import POLICY_DIR, POLICY_FILES
from app.services.catalog import get_product

SOURCE_OWNER = 'shopping-assistant-policy-v1'
MIN_SIMILARITY = 0.50  # 本地 BGE 少量演示样本验证；不是可信概率或通用准确率保证。

def split_text(text: str) -> list[str]:
    """按段落合并，长段切为最多600字符，保持标题上下文。"""
    paragraphs = [p.strip() for p in text.strip().split('\n\n') if p.strip()]
    title = paragraphs[0]
    chunks = []
    buffer = title
    for paragraph in paragraphs[1:]:
        for start in range(0, len(paragraph), 500):
            part = paragraph[start:start+500]
            if len(buffer) + len(part) + 2 > 600:
                chunks.append(buffer)
                buffer = title
            buffer += '\n\n' + part
    if buffer != title or not chunks:
        chunks.append(buffer)
    return chunks

async def _embed(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    if not settings.embedding_dimension:
        raise DomainError('KNOWLEDGE_UNAVAILABLE', 'embedding 未完成真实维度探测；请本地配置并探测后设置 EMBEDDING_DIMENSION', 503)
    try:
        return await EmbeddingAdapter().embed_texts(texts)
    except DomainError:
        raise
    except Exception as error:
        # 不输出上游异常正文，避免 URL/请求携带凭据。
        raise DomainError('EMBEDDING_FAILED', f'真实 embedding 请求失败（{type(error).__name__}，HTTP {getattr(error,"status_code","未知")}）；本次未完成，未使用替代向量', 503) from None

async def ingest_documents(paths: list[Path]) -> list[KnowledgeSource]:
    """只导入明确政策；全部向量成功后事务内替换本来源对应文档。"""
    allowed = {(POLICY_DIR / name).resolve(): doc for doc, name in POLICY_FILES.items()}
    if not paths or len(set(p.resolve() for p in paths)) != len(paths) or any(p.resolve() not in allowed for p in paths):
        raise DomainError('INVALID_ARGUMENT', '只允许明确登记的三个 .policy.md 政策文件，拒绝目录说明或工作文档', 422)
    entries = []
    for path in paths:
        text = path.read_text(encoding='utf-8-sig').strip()
        if '项目演示政策' not in text or '不代表真实商家' not in text:
            raise DomainError('INVALID_ARGUMENT', '资料缺少演示政策声明', 422)
        for index, chunk in enumerate(split_text(text)):
            document_id = allowed[path.resolve()]
            chunk_id = document_id + '-' + sha256((str(index)+chunk).encode()).hexdigest()[:20]
            entries.append((chunk_id, document_id, text.splitlines()[0].lstrip('# '), chunk))
    vectors = await _embed([entry[3] for entry in entries])
    settings = get_settings()
    async with db.get_connection() as connection:
        async with connection.transaction():
            # 同语料并发导入串行；任何模型/维度变更必须整套重新导入。
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (SOURCE_OWNER,))
            cursor = await connection.execute('SELECT DISTINCT embedding_model,embedding_dimension FROM knowledge_chunks WHERE source_owner=%s', (SOURCE_OWNER,))
            existing = await cursor.fetchall()
            if existing and any(row != (settings.embedding_model, settings.embedding_dimension) for row in existing) and set(allowed[p.resolve()] for p in paths) != set(POLICY_FILES):
                raise DomainError('KNOWLEDGE_MODEL_MISMATCH', '模型或维度改变时必须重新导入全部演示政策', 409)
            for document_id in {e[1] for e in entries}:
                cursor = await connection.execute('SELECT 1 FROM knowledge_chunks WHERE document_id=%s AND source_owner IS DISTINCT FROM %s LIMIT 1', (document_id, SOURCE_OWNER))
                if await cursor.fetchone():
                    raise DomainError('KNOWLEDGE_SOURCE_CONFLICT', '该文档ID由其他来源持有，未覆盖', 409)
                await connection.execute('DELETE FROM knowledge_chunks WHERE document_id=%s AND source_owner=%s', (document_id, SOURCE_OWNER))
            for entry, vector in zip(entries, vectors, strict=True):
                await connection.execute('INSERT INTO knowledge_chunks(chunk_id,document_id,title,excerpt,embedding,embedding_model,embedding_dimension,source_owner) VALUES (%s,%s,%s,%s,%s::vector,%s,%s,%s)', (*entry,json.dumps(vector),settings.embedding_model,settings.embedding_dimension,SOURCE_OWNER))
    return await list_sources()

async def search_knowledge(query: str, product_id: str | None = None, top_k: int = 3) -> list[KnowledgeHit]:
    """按同模型同维度余弦距离检索；不足证据返回空，不返回旧引用。"""
    if not query.strip() or not 1 <= top_k <= 3:
        raise DomainError('INVALID_ARGUMENT', '需要非空查询，top_k 为1–3', 422)
    if product_id:
        product = await get_product(product_id)
        if product.policy_id not in ('demo-return-7-days', 'demo-no-return'):
            return []
    settings = get_settings()
    vector = (await _embed([query]))[0]
    async with db.get_connection() as connection:
        cursor = await connection.execute('SELECT DISTINCT embedding_model,embedding_dimension FROM knowledge_chunks WHERE source_owner=%s', (SOURCE_OWNER,))
        corpus = await cursor.fetchall()
        if not corpus:
            raise DomainError('KNOWLEDGE_UNAVAILABLE', '演示政策尚未真实入库，请运行 ingest_knowledge', 503)
        if any(row != (settings.embedding_model, settings.embedding_dimension) for row in corpus):
            raise DomainError('KNOWLEDGE_MODEL_MISMATCH', '当前 embedding 模型/维度与语料不一致，需要重新入库', 503)
        cursor = await connection.execute('SELECT chunk_id,document_id,title,excerpt,1-(embedding <=> %s::vector) AS score FROM knowledge_chunks WHERE source_owner=%s AND embedding_model=%s AND embedding_dimension=%s ORDER BY embedding <=> %s::vector,chunk_id LIMIT %s', (json.dumps(vector),SOURCE_OWNER,settings.embedding_model,settings.embedding_dimension,json.dumps(vector),top_k))
        rows = await cursor.fetchall()
    return [KnowledgeHit(chunk_id=r[0],document_id=r[1],title=r[2],excerpt=r[3],score=r[4]) for r in rows if r[4] >= MIN_SIMILARITY]

async def list_sources() -> list[KnowledgeSource]:
    async with db.get_connection() as connection:
        cursor = await connection.execute('SELECT document_id,title,count(*) FROM knowledge_chunks WHERE source_owner=%s GROUP BY document_id,title ORDER BY document_id', (SOURCE_OWNER,))
        return [KnowledgeSource(document_id=r[0],title=r[1],chunk_count=r[2]) for r in await cursor.fetchall()]
