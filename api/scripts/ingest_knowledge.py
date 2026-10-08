"""白名单政策真实入库；复用池与 Windows Selector 循环。"""
import asyncio
from app import db
from app.services.knowledge import ingest_documents
from app.services.policies import POLICY_DIR, POLICY_FILES

async def main() -> None:
    await db.open_pool()
    try:
        await db.init_schema()
        sources = await ingest_documents([POLICY_DIR / file for file in POLICY_FILES.values()])
        print([source.model_dump() for source in sources])
    finally:
        await db.close_pool()

if __name__ == '__main__':
    asyncio.run(main(), loop_factory=db.create_event_loop)
