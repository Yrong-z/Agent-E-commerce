"""准备入口的配置门槛；不启动服务、不调用模型或写业务库。"""
import pytest
from scripts import prepare_local
from app.config import Settings


def test_setup_requires_chat_but_manual_start_remains_available(tmp_path, monkeypatch, capsys):
    model = tmp_path / 'model'
    model.mkdir()
    for name in ('config.json', 'tokenizer.json', 'model.safetensors'):
        (model / name).write_text('仅配置检查夹具', encoding='utf-8')
    (tmp_path / '.env').write_text('POSTGRES_PASSWORD=demo\nDATABASE_URL=postgresql://demo\n', encoding='utf-8')
    monkeypatch.setattr(prepare_local, 'PROJECT_ROOT', tmp_path)
    # 配置检查夹具不代表模型可推理；实际模型/服务另做运行验收。
    monkeypatch.setattr(prepare_local, 'dotenv_values', lambda _: {
        'EMBEDDING_MODEL_DIR': str(model), 'POSTGRES_PASSWORD': 'demo',
        'DATABASE_URL': 'postgresql://demo', 'CHAT_API_KEY': '',
    })
    with pytest.raises(ValueError, match='CHAT_BASE_URL、CHAT_API_KEY、CHAT_MODEL'):
        prepare_local.preflight(require_chat=True)
    prepare_local.preflight()
    assert '聊天将禁用' in capsys.readouterr().out
    def invalid_settings():
        return Settings(embedding_dimension='private-sensitive-test')
    monkeypatch.setattr(prepare_local, 'get_settings', invalid_settings)
    with pytest.raises(ValueError) as invalid:
        prepare_local.preflight()
    assert 'embedding_dimension' in str(invalid.value)
    assert 'private-sensitive-test' not in str(invalid.value)


def test_setup_does_not_download_missing_model(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_local, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(prepare_local, 'dotenv_values', lambda _: {})
    with pytest.raises(ValueError, match='不自动下载'):
        prepare_local.preflight(require_chat=True)
    assert not (tmp_path / 'data/embedding-model').exists()
