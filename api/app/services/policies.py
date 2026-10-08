"""项目演示政策：结构化规则与公开资料的唯一映射。"""
from pathlib import Path
from app.config import PROJECT_ROOT
from app.schemas import PolicyReference

POLICY_DIR = PROJECT_ROOT / 'data' / 'knowledge'
POLICY_FILES = {
    'demo-policy-return': 'return.policy.md',
    'demo-policy-refund': 'refund.policy.md',
    'demo-policy-warranty': 'warranty.policy.md',
}
POLICIES = {
    'demo-return-7-days': {'return_days': 7, 'return_allowed': True, 'source_ids': ['demo-policy-return', 'demo-policy-refund']},
    'demo-no-return': {'return_days': 0, 'return_allowed': False, 'source_ids': ['demo-policy-return']},
}

def policy_reference(document_id: str) -> PolicyReference:
    text = (POLICY_DIR / POLICY_FILES[document_id]).read_text(encoding='utf-8').strip()
    return PolicyReference(document_id=document_id, title=text.splitlines()[0].lstrip('# '), excerpt=text)
