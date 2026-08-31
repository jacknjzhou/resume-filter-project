from app.config import Settings

def test_settings_defaults(monkeypatch):
    # 容器内跑测试时，compose env_file 会注入 LLM_API_KEY 等 env 覆盖默认值，
    # 先清掉这些变量，才能验证 Settings 自身的默认值
    for var in ("LLM_API_KEY", "LLM_VLM_MODEL", "OCR_CONFIDENCE_THRESHOLD",
                "STEP_TIMEOUT", "MAX_CONCURRENCY"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(
        database_url="sqlite:///test.db",
        llm_base_url="http://fake/v1",
        llm_model="test-model",
        _env_file=None,
    )
    assert s.llm_api_key == "EMPTY"
    assert s.ocr_confidence_threshold == 0.85
    assert s.step_timeout == 120
    assert s.max_concurrency == 3
    assert s.llm_vlm_model == ""

def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("OCR_CONFIDENCE_THRESHOLD", "0.9")
    monkeypatch.setenv("STEP_TIMEOUT", "60")
    s = Settings(
        database_url="sqlite:///test.db",
        llm_base_url="http://fake/v1",
        llm_model="m",
        _env_file=None,
    )
    assert s.ocr_confidence_threshold == 0.9
    assert s.step_timeout == 60
