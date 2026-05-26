from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DEFAULTS = {
    "CLASSIFIER_CONFIG_ROOT": REPO_ROOT / "config",
    "CLASSIFIER_OUTPUT_ROOT": REPO_ROOT / ".runtime" / "classifier",
    "CLASSIFIER_INPUT_ROOT": REPO_ROOT / ".runtime" / "input" / "api",
    "CLASSIFIER_VAULT_ROOT": REPO_ROOT / ".runtime" / "vault",
}


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default))


def _default_path(name: str, container_default: str) -> Path:
    if name in os.environ:
        return Path(os.environ[name])
    if os.name == "nt":
        return LOCAL_DEFAULTS[name]
    container_path = Path(container_default)
    if container_path.exists():
        return container_path
    return LOCAL_DEFAULTS[name]


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
    codex_arbiter_enabled: bool

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
    def taxonomy_sources_path(self) -> Path:
        return self.config_root / "taxonomy-sources.json"

    @property
    def external_taxonomy_aliases_path(self) -> Path:
        return self.config_root / "external-taxonomy-aliases.json"

    @property
    def external_taxonomy_prune_path(self) -> Path:
        return self.config_root / "external-taxonomy-prune.json"

    @property
    def corrections_path(self) -> Path:
        return self.config_root / "corrections.jsonl"

    @property
    def examples_path(self) -> Path:
        return self.config_root / "examples.jsonl"

    @property
    def reviewed_examples_report_path(self) -> Path:
        return self.config_root / "reviewed-examples-report.json"

    @property
    def example_mining_report_path(self) -> Path:
        return self.config_root / "example-mining-report.json"

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
    def taxonomy_router_report_path(self) -> Path:
        return self.config_root / "taxonomy-router-report.json"

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
        config_root=_default_path("CLASSIFIER_CONFIG_ROOT", "/config"),
        output_root=_default_path("CLASSIFIER_OUTPUT_ROOT", "/output"),
        input_root=_default_path("CLASSIFIER_INPUT_ROOT", "/input/api"),
        vault_root=_default_path("CLASSIFIER_VAULT_ROOT", "/vault"),
        api_token=os.getenv("CLASSIFIER_API_TOKEN", ""),
        ollama_url=os.getenv("OLLAMA_URL", "http://ollama:11434").strip() or "http://ollama:11434",
        shadow_worker_enabled=_env_flag("ENABLE_SHADOW_WORKER", "1"),
        shadow_worker_interval_seconds=shadow_worker_interval_seconds,
        codex_arbiter_enabled=_env_flag("CODEX_ARBITER_ENABLED", "0"),
    )
