"""启动前检查配置并按空库状态复用已有种子、探测与入库实现。"""
import asyncio
import sys
from pathlib import Path
from dotenv import dotenv_values
from pydantic import ValidationError
from app import db
from app.config import PROJECT_ROOT, get_settings
from app.services.knowledge import SOURCE_OWNER


def preflight(require_chat: bool = False) -> None:
    values = dotenv_values(PROJECT_ROOT / '.env')
    model = values.get('EMBEDDING_MODEL_DIR')
    directory = Path(model) if model else PROJECT_ROOT / 'data/embedding-model'
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    if not directory.is_dir() or not all((directory / n).is_file() for n in ('config.json', 'tokenizer.json')) or not any(directory.glob('*.bin')) and not any(directory.glob('*.safetensors')):
        raise ValueError('模型目录缺失或不完整；在 .env 填写 EMBEDDING_MODEL_DIR，准备配置、分词器及权重，不自动下载')
    if not values.get('POSTGRES_PASSWORD') or not values.get('DATABASE_URL'):
        raise ValueError('请在 .env 填写 POSTGRES_PASSWORD 与一致的 DATABASE_URL')
    if not all(values.get(n) for n in ('CHAT_BASE_URL', 'CHAT_API_KEY', 'CHAT_MODEL')):
        if require_chat:
            raise ValueError('聊天配置不完整；请在根目录 .env 填写 CHAT_BASE_URL、CHAT_API_KEY、CHAT_MODEL，再运行 setup.cmd；start.cmd 仍可运行手动查询')
        print('聊天配置不完整：聊天将禁用；手动商品、订单与售后仍可用。')
    try:
        get_settings()  # 复用实际配置校验，只提示字段名称，不打印输入值。
    except ValidationError as error:
        fields = ', '.join('.'.join(map(str, item['loc'])) for item in error.errors(include_input=False))
        raise ValueError(f'配置字段无效：{fields}；请编辑根目录 .env 后重试') from None
    print('配置与只读模型目录检查通过。')


async def prepare() -> None:
    await db.open_pool()
    try:
        await db.init_schema()
        async with db.get_connection() as connection:
            product_count = (await (await connection.execute('SELECT count(*) FROM products')).fetchone())[0]
            order_count = (await (await connection.execute('SELECT count(*) FROM orders')).fetchone())[0]
            chunks = await (await connection.execute('SELECT embedding_model, embedding_dimension FROM knowledge_chunks WHERE source_owner=%s', (SOURCE_OWNER,))).fetchall()
        if product_count == order_count == 0:
            from scripts.seed_demo import seed_demo_data
            await seed_demo_data()
            print('空商品与订单库：已复用幂等种子完成初始化。')
        elif not product_count or not order_count:
            raise ValueError('商品或订单数据仅部分存在；停止自动初始化，按 README 有意补齐，避免刷新已有订单日期')
        else:
            print('已有商品与订单：跳过种子，签收日期保持。')
        settings = get_settings()
        if chunks:
            if not settings.embedding_dimension or any(model != settings.embedding_model or dim != settings.embedding_dimension for model, dim in chunks):
                raise ValueError('已入库模型/维度与配置不一致；按 README 有意探测和重新入库，不自动覆盖知识')
            print('已有本项目知识：跳过探测与入库。')
        else:
            if not settings.embedding_dimension:
                from scripts.probe_embedding import main as probe
                await probe(True)
            from app.services.knowledge import ingest_documents
            from app.services.policies import POLICY_DIR, POLICY_FILES
            await ingest_documents([POLICY_DIR / name for name in POLICY_FILES.values()])
            print('本项目知识为空：已复用真实探测/入库实现完成初始化。')
    finally:
        await db.close_pool()


if __name__ == '__main__':
    try:
        preflight(require_chat='--require-chat' in sys.argv)
        if '--preflight' not in sys.argv:
            asyncio.run(prepare(), loop_factory=db.create_event_loop)
    except Exception as error:
        # 不输出数据库连接串或外部请求内容。
        print(str(error) if isinstance(error, ValueError) else f'准备失败（{type(error).__name__}），检查本地配置及服务后显式重试。', file=sys.stderr)
        raise SystemExit(1) from None
