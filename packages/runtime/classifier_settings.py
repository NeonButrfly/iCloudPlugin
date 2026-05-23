from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default))


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() not in {"", "0", "false", "no", "off"}


@dataclass(frozen=True)
class ClassifierRuntimeSettings:
    config_root: Path
    output_root: Path
    input_root: Path
    vault_root: Path
    api_token: str
    ollama_url: str
    shadow_worker_enabled: bool
    shadow_worker_interval_seconds: int

    @property
    def categories_path(self) -> Path:
        return self.config_root / "categories.txt"

    @property
    def local_categories_path(self) -> Path:
        return self.config_root / "categories.local.txt"

    @property
    def category_groups_path(self) -> Path:
        return self.config_root / "category-groups.json"

    @property
    def corrections_path(self) -> Path:
        return self.config_root / "corrections.jsonl"

    @property
    def examples_path(self) -> Path:
        return self.config_root / "examples.jsonl"

    @property
    def hybrid_gating_path(self) -> Path:
        return self.config_root / "hybrid-gating.json"

    @property
    def heuristic_rules_path(self) -> Path:
        return self.config_root / "heuristic-rules.json"

    @property
    def lightgbm_model_path(self) -> Path:
        return self.config_root / "lightgbm-classifier.joblib"

    @property
    def lightgbm_report_path(self) -> Path:
        return self.config_root / "lightgbm-training-report.json"

    @property
    def taxonomy_router_model_path(self) -> Path:
        return self.config_root / "taxonomy-router.joblib"

    @property
    def shadow_queue_dir(self) -> Path:
        return self.output_root / "shadow-queue"

    @property
    def shadow_comparisons_path(self) -> Path:
        return self.output_root / "shadow-comparisons.jsonl"

    @property
    def readiness_report_path(self) -> Path:
        return self.output_root / "readiness-report.json"

    @property
    def retrain_dir(self) -> Path:
        return self.output_root / "retrain"

    @property
    def manifest_path(self) -> Path:
        return self.output_root / "manifest.jsonl"

    @property
    def classification_index_path(self) -> Path:
        return self.vault_root / "Classification Index.md"


def load_classifier_runtime_settings() -> ClassifierRuntimeSettings:
    interval_text = os.getenv("SHADOW_WORKER_INTERVAL_SECONDS", "15").strip()
    try:
        shadow_worker_interval_seconds = int(interval_text)
    except ValueError:
        shadow_worker_interval_seconds = 15

    return ClassifierRuntimeSettings(
        config_root=_env_path("CLASSIFIER_CONFIG_ROOT", "/config"),
        output_root=_env_path("CLASSIFIER_OUTPUT_ROOT", "/output"),
        input_root=_env_path("CLASSIFIER_INPUT_ROOT", "/input/api"),
        vault_root=_env_path("CLASSIFIER_VAULT_ROOT", "/vault"),
        api_token=os.getenv("CLASSIFIER_API_TOKEN", ""),
        ollama_url=os.getenv("OLLAMA_URL", "http://ollama:11434").strip() or "http://ollama:11434",
        shadow_worker_enabled=_env_flag("ENABLE_SHADOW_WORKER", "1"),
        shadow_worker_interval_seconds=shadow_worker_interval_seconds,
    )
