import os
from importlib import import_module
from pathlib import Path


def test_classifier_runtime_paths_default_to_existing_locations(monkeypatch):
    monkeypatch.delenv("CLASSIFIER_CONFIG_ROOT", raising=False)
    monkeypatch.delenv("CLASSIFIER_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLASSIFIER_INPUT_ROOT", raising=False)
    monkeypatch.delenv("CLASSIFIER_VAULT_ROOT", raising=False)
    monkeypatch.delenv("CODEX_ARBITER_ENABLED", raising=False)

    module = import_module("packages.runtime.classifier_settings")
    settings = module.load_classifier_runtime_settings()

    if os.name == "nt":
        expected_config = module.REPO_ROOT / "config"
        expected_output = module.REPO_ROOT / ".runtime" / "classifier"
        expected_input = module.REPO_ROOT / ".runtime" / "input" / "api"
        expected_vault = module.REPO_ROOT / ".runtime" / "vault"
    else:
        expected_config = Path("/config") if Path("/config").exists() else module.REPO_ROOT / "config"
        expected_output = Path("/output") if Path("/output").exists() else module.REPO_ROOT / ".runtime" / "classifier"
        expected_input = Path("/input/api") if Path("/input/api").exists() else module.REPO_ROOT / ".runtime" / "input" / "api"
        expected_vault = Path("/vault") if Path("/vault").exists() else module.REPO_ROOT / ".runtime" / "vault"

    assert settings.config_root == expected_config
    assert settings.output_root == expected_output
    assert settings.input_root == expected_input
    assert settings.vault_root == expected_vault
    assert settings.manifest_path == expected_output / "manifest.jsonl"
    assert settings.readiness_report_path == expected_output / "readiness-report.json"
    assert settings.classify_model == "qwen2.5:3b"
    assert settings.vision_model == "qwen2.5vl:3b"
    assert settings.codex_arbiter_enabled is False


def test_classifier_runtime_paths_allow_role_specific_overrides(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_CONFIG_ROOT", "/srv/config")
    monkeypatch.setenv("CLASSIFIER_OUTPUT_ROOT", "/srv/output")
    monkeypatch.setenv("CLASSIFIER_INPUT_ROOT", "/srv/input")
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", "/srv/vault")

    module = import_module("packages.runtime.classifier_settings")
    settings = module.load_classifier_runtime_settings()

    assert settings.config_root == Path("/srv/config")
    assert settings.output_root == Path("/srv/output")
    assert settings.input_root == Path("/srv/input")
    assert settings.vault_root == Path("/srv/vault")
    assert settings.shadow_queue_dir == Path("/srv/output/shadow-queue")


def test_classifier_runtime_paths_support_bundled_and_artifact_overrides(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_CONFIG_ROOT", "/srv/config")
    monkeypatch.setenv("CLASSIFIER_OUTPUT_ROOT", "/srv/output")
    monkeypatch.setenv("CLASSIFIER_INPUT_ROOT", "/srv/input")
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", "/srv/vault")
    monkeypatch.setenv("CLASSIFIER_BUNDLED_CONFIG_ROOT", "/srv/app-config")
    monkeypatch.setenv("CLASSIFIER_ARTIFACT_ROOT", "/srv/artifacts")

    module = import_module("packages.runtime.classifier_settings")
    settings = module.load_classifier_runtime_settings()

    assert settings.bundled_config_root == Path("/srv/app-config")
    assert settings.artifact_root == Path("/srv/artifacts")
    assert settings.lightgbm_model_path == Path("/srv/artifacts/lightgbm-classifier.joblib")
    assert settings.lightgbm_report_path == Path("/srv/artifacts/lightgbm-training-report.json")
    assert settings.hybrid_gating_path == Path("/srv/artifacts/hybrid-gating.json")
    assert settings.heuristic_rules_path == Path("/srv/artifacts/heuristic-rules.json")
    assert settings.readable_config_path("lightgbm-classifier.joblib", include_artifact=False) == Path(
        "/srv/config/lightgbm-classifier.joblib"
    )


def test_codex_arbiter_requires_explicit_enable_flag(monkeypatch):
    module = import_module("packages.runtime.classifier_settings")

    monkeypatch.setenv("CODEX_ARBITER_ENABLED", "0")
    assert module.load_classifier_runtime_settings().codex_arbiter_enabled is False

    monkeypatch.setenv("CODEX_ARBITER_ENABLED", "1")
    assert module.load_classifier_runtime_settings().codex_arbiter_enabled is True


def test_codex_arbiter_runtime_settings_support_command_and_timeout_overrides(monkeypatch):
    module = import_module("packages.runtime.classifier_settings")

    monkeypatch.setenv("CODEX_ARBITER_COMMAND", "codex exec --skip-git-repo-check")
    monkeypatch.setenv("CODEX_ARBITER_TIMEOUT_SECONDS", "45")

    settings = module.load_classifier_runtime_settings()

    assert settings.codex_arbiter_command == "codex exec --skip-git-repo-check"
    assert settings.codex_arbiter_timeout_seconds == 45


def test_classifier_runtime_settings_support_model_overrides(monkeypatch):
    module = import_module("packages.runtime.classifier_settings")

    monkeypatch.setenv("CLASSIFY_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("VISION_MODEL", "qwen2.5vl:7b")

    settings = module.load_classifier_runtime_settings()

    assert settings.classify_model == "qwen2.5:7b"
    assert settings.vision_model == "qwen2.5vl:7b"
