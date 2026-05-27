from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DEFAULTS = {
    "CLASSIFIER_CONFIG_ROOT": REPO_ROOT / "config",
    "CLASSIFIER_OUTPUT_ROOT": REPO_ROOT / ".runtime" / "classifier",
    "CLASSIFIER_INPUT_ROOT": REPO_ROOT / ".runtime" / "input" / "api",
    "CLASSIFIER_SOURCE_ROOT": REPO_ROOT / ".runtime" / "source",
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


def _default_bundled_config_root(config_root: Path) -> Path:
    if "CLASSIFIER_BUNDLED_CONFIG_ROOT" in os.environ:
        return Path(os.environ["CLASSIFIER_BUNDLED_CONFIG_ROOT"])
    if os.name == "nt":
        return config_root
    bundled = Path("/app/config")
    if bundled.exists():
        return bundled
    return config_root


def _default_artifact_root(config_root: Path, output_root: Path) -> Path:
    if "CLASSIFIER_ARTIFACT_ROOT" in os.environ:
        return Path(os.environ["CLASSIFIER_ARTIFACT_ROOT"])
    if os.name == "nt":
        return config_root
    return output_root / "_artifacts"


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() not in {"", "0", "false", "no", "off"}


@dataclass(frozen=True)
class ClassifierRuntimeSettings:
    config_root: Path
    bundled_config_root: Path
    artifact_root: Path
    output_root: Path
    input_root: Path
    source_root: Path
    vault_root: Path
    api_token: str
    ollama_url: str
    shadow_worker_enabled: bool
    shadow_worker_interval_seconds: int
    codex_arbiter_enabled: bool

    def resolve_existing_config_path(self, filename: str, *, include_artifact: bool = True) -> Path | None:
        candidates = []
        if include_artifact:
            candidates.append(self.artifact_root / filename)
        candidates.extend(
            [
                self.config_root / filename,
                self.bundled_config_root / filename,
            ]
        )
        seen: set[Path] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.exists():
                return candidate
        return None

    def artifact_path(self, filename: str) -> Path:
        return self.artifact_root / filename

    def readable_config_path(self, filename: str, *, include_artifact: bool = True) -> Path:
        return self.resolve_existing_config_path(filename, include_artifact=include_artifact) or (self.config_root / filename)

    @property
    def categories_path(self) -> Path:
        return self.readable_config_path("categories.txt", include_artifact=False)

    @property
    def local_categories_path(self) -> Path:
        return self.readable_config_path("categories.local.txt", include_artifact=False)

    @property
    def category_groups_path(self) -> Path:
        return self.readable_config_path("category-groups.json", include_artifact=False)

    @property
    def taxonomy_sources_path(self) -> Path:
        return self.readable_config_path("taxonomy-sources.json", include_artifact=False)

    @property
    def external_taxonomy_aliases_path(self) -> Path:
        return self.readable_config_path("external-taxonomy-aliases.json")

    @property
    def external_taxonomy_prune_path(self) -> Path:
        return self.readable_config_path("external-taxonomy-prune.json")

    @property
    def corrections_path(self) -> Path:
        return self.readable_config_path("corrections.jsonl")

    @property
    def examples_path(self) -> Path:
        return self.readable_config_path("examples.jsonl")

    @property
    def reviewed_examples_report_path(self) -> Path:
        return self.readable_config_path("reviewed-examples-report.json")

    @property
    def example_mining_report_path(self) -> Path:
        return self.readable_config_path("example-mining-report.json")

    @property
    def hybrid_gating_path(self) -> Path:
        return self.artifact_path("hybrid-gating.json")

    @property
    def heuristic_rules_path(self) -> Path:
        return self.artifact_path("heuristic-rules.json")

    @property
    def lightgbm_model_path(self) -> Path:
        return self.artifact_path("lightgbm-classifier.joblib")

    @property
    def lightgbm_report_path(self) -> Path:
        return self.artifact_path("lightgbm-training-report.json")

    @property
    def taxonomy_router_model_path(self) -> Path:
        return self.artifact_path("taxonomy-router.joblib")

    @property
    def taxonomy_router_report_path(self) -> Path:
        return self.artifact_path("taxonomy-router-report.json")

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

    config_root = _default_path("CLASSIFIER_CONFIG_ROOT", "/config")
    output_root = _default_path("CLASSIFIER_OUTPUT_ROOT", "/output")

    return ClassifierRuntimeSettings(
        config_root=config_root,
        bundled_config_root=_default_bundled_config_root(config_root),
        artifact_root=_default_artifact_root(config_root, output_root),
        output_root=output_root,
        input_root=_default_path("CLASSIFIER_INPUT_ROOT", "/input/api"),
        source_root=_default_path("CLASSIFIER_SOURCE_ROOT", "/source"),
        vault_root=_default_path("CLASSIFIER_VAULT_ROOT", "/vault"),
        api_token=os.getenv("CLASSIFIER_API_TOKEN", ""),
        ollama_url=os.getenv("OLLAMA_URL", "http://ollama:11434").strip() or "http://ollama:11434",
        shadow_worker_enabled=_env_flag("ENABLE_SHADOW_WORKER", "1"),
        shadow_worker_interval_seconds=shadow_worker_interval_seconds,
        codex_arbiter_enabled=_env_flag("CODEX_ARBITER_ENABLED", "0"),
    )
