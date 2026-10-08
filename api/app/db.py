"""PostgreSQL 连接池、短事务与无业务数据的基础表。"""
from contextlib import asynccontextmanager
import asyncio
import sys
from psycopg_pool import AsyncConnectionPool
from app.config import get_settings

pool: AsyncConnectionPool | None = None

def create_event_loop() -> asyncio.AbstractEventLoop:
    """Windows 使用 psycopg 支持的 Selector 循环；仅配置应用进程。"""
    return asyncio.SelectorEventLoop() if sys.platform == 'win32' else asyncio.new_event_loop()

async def open_pool() -> None:
    """启动连接池，数据库未就绪时保持应用可诊断。"""
    global pool
    pool = AsyncConnectionPool(get_settings().database_url.get_secret_value(), min_size=0, max_size=4, timeout=3, open=False, kwargs={'connect_timeout': 3})
    await pool.open()

async def close_pool() -> None:
    """退出时释放连接。"""
    if pool is not None:
        await pool.close()

@asynccontextmanager
async def get_connection():
    """获取连接；正常退出提交，异常回滚。"""
    if pool is None:
        raise RuntimeError('数据库连接池尚未启动')
    async with pool.connection() as connection:
        yield connection

async def init_schema() -> None:
    """创建扩展与六张空表；不初始化种子或知识向量。"""
    async with get_connection() as connection:
        await connection.execute('CREATE EXTENSION IF NOT EXISTS vector')
        await connection.execute('CREATE TABLE IF NOT EXISTS products (product_id text PRIMARY KEY, payload jsonb NOT NULL)')
        await connection.execute('CREATE TABLE IF NOT EXISTS orders (order_id text PRIMARY KEY, customer_id text NOT NULL, payload jsonb NOT NULL)')
        await connection.execute('CREATE TABLE IF NOT EXISTS sessions (session_id text PRIMARY KEY, customer_id text NOT NULL, state jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())')
        await connection.execute('CREATE TABLE IF NOT EXISTS knowledge_chunks (chunk_id text PRIMARY KEY, document_id text NOT NULL, title text NOT NULL, excerpt text NOT NULL, embedding vector, embedding_model text, embedding_dimension integer)')
        await connection.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS source_owner text")
        await connection.execute('CREATE TABLE IF NOT EXISTS after_sales (preview_id text PRIMARY KEY, customer_id text NOT NULL, session_id text NOT NULL, application_id text UNIQUE, status text NOT NULL, payload jsonb NOT NULL)')
        await connection.execute('CREATE TABLE IF NOT EXISTS traces (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, request_id text NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now())')

async def check_database() -> tuple[bool, bool]:
    """检查实际数据库连接及向量运算，不暴露连接字符串。"""
    async with get_connection() as connection:
        await connection.execute('SELECT 1')
        cursor = await connection.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        if await cursor.fetchone() is None:
            return True, False
        cursor = await connection.execute("SELECT '[1,2,3]'::vector <-> '[1,2,3]'::vector")
        return True, (await cursor.fetchone())[0] == 0
