import pytest
from app import settings_store
from app.config import get_settings

EDITABLE = ["llm_base_url", "llm_api_key", "llm_model", "llm_vlm_model",
            "llm_timeout", "ocr_base_url", "ocr_confidence_threshold",
            "step_timeout", "max_concurrency"]


@pytest.fixture
def restore_settings():
    s = get_settings()
    snapshot = {k: getattr(s, k) for k in EDITABLE}
    yield s
    for k, v in snapshot.items():
        setattr(s, k, v)  # 测试后恢复，避免污染其他用例


def test_save_and_load_overrides(db_session):
    settings_store.save_overrides(db_session, {"llm_model": "qwen3-32b",
                                               "max_concurrency": "5"})
    assert settings_store.load_overrides(db_session) == {
        "llm_model": "qwen3-32b", "max_concurrency": "5"}


def test_save_overrides_rejects_unknown_key(db_session):
    with pytest.raises(ValueError):
        settings_store.save_overrides(db_session, {"database_url": "x"})


def test_apply_to_settings_coerces_types(db_session, restore_settings):
    settings_store.save_overrides(db_session, {"step_timeout": "60",
                                               "llm_timeout": "30.5"})
    settings_store.apply_to_settings(
        restore_settings, settings_store.load_overrides(db_session))
    assert restore_settings.step_timeout == 60
    assert isinstance(restore_settings.step_timeout, int)
    assert restore_settings.llm_timeout == 30.5


def test_apply_to_settings_ignores_unknown(db_session, restore_settings):
    before = restore_settings.llm_model
    settings_store.apply_to_settings(restore_settings, {"llm_model2": "x"})
    assert restore_settings.llm_model == before


def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from tests.conftest import _testing_session
    app.dependency_overrides[get_db] = _testing_session
    return TestClient(app)


def test_get_settings_returns_editable(db_session, restore_settings):
    c = _client()
    try:
        resp = c.get("/api/settings")
        assert resp.status_code == 200
        editable = resp.json()["editable"]
        assert set(editable) == set(EDITABLE)
        assert "value" in editable["llm_model"] and "overridden" in editable["llm_model"]
        assert editable["llm_model"]["overridden"] is False
    finally:
        from app.main import app
        from app.db import get_db
        app.dependency_overrides.pop(get_db, None)


def test_put_settings_persists_and_applies(db_session, restore_settings):
    c = _client()
    try:
        resp = c.put("/api/settings",
                     json={"llm_model": "glm-4", "max_concurrency": 6})
        assert resp.status_code == 200, resp.text
        # 1) DB 持久化
        assert settings_store.load_overrides(db_session)["llm_model"] == "glm-4"
        # 2) 单例生效
        assert restore_settings.llm_model == "glm-4"
        assert restore_settings.max_concurrency == 6
        # 3) GET 能看到 overridden 标记
        body = c.get("/api/settings").json()["editable"]
        assert body["llm_model"]["overridden"] is True
        assert body["llm_base_url"]["overridden"] is False
    finally:
        from app.main import app
        from app.db import get_db
        app.dependency_overrides.pop(get_db, None)


def test_put_settings_rejects_unknown_and_invalid(db_session, restore_settings):
    c = _client()
    try:
        assert c.put("/api/settings", json={"database_url": "x"}).status_code == 422
        assert c.put("/api/settings", json={"llm_timeout": "abc"}).status_code == 422
        assert c.put("/api/settings", json={"max_concurrency": 0}).status_code == 422
        assert c.put("/api/settings", json={"ocr_confidenceence": 2}).status_code == 422
    finally:
        from app.main import app
        from app.db import get_db
        app.dependency_overrides.pop(get_db, None)
