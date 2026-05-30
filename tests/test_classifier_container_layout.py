from pathlib import Path


def test_classifier_dockerfile_copies_shared_packages_for_monorepo_runtime():
    repo_root = Path(__file__).resolve().parents[1]
    dockerfile = repo_root / "apps" / "classifier" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "COPY packages /app/packages" in text
    assert "COPY src /app/src" in text
    assert "ENV PYTHONPATH=/app:/app/src" in text


def test_classifier_dockerfile_uses_cmd_so_api_service_can_override_startup():
    repo_root = Path(__file__).resolve().parents[1]
    dockerfile = repo_root / "apps" / "classifier" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert 'CMD ["python", "/app/apps/classifier/classify-to-obsidian.py"]' in text
    assert "ENTRYPOINT" not in text


def test_classifier_runtime_installs_paddleocr_cpu_dependencies():
    repo_root = Path(__file__).resolve().parents[1]
    requirements = (repo_root / "apps" / "classifier" / "requirements.txt").read_text(encoding="utf-8")
    dockerfile = (repo_root / "apps" / "classifier" / "Dockerfile").read_text(encoding="utf-8")

    assert "paddleocr" in requirements
    assert "pytesseract" in requirements
    assert "sqlalchemy" in requirements
    assert "paddlepaddle" in dockerfile


def test_classifier_role_compose_includes_dedicated_shadow_worker():
    repo_root = Path(__file__).resolve().parents[1]
    classifier_compose = (repo_root / "deploy" / "roles" / "classifier" / "docker-compose.yml").read_text(encoding="utf-8")
    combined_compose = (repo_root / "deploy" / "roles" / "combined" / "docker-compose.yml").read_text(encoding="utf-8")

    assert "shadow-worker:" in classifier_compose
    assert "apps.classifier.shadow_worker" in classifier_compose
    assert "PYTHONPATH=/app:/app/src" in classifier_compose
    assert "shadow-worker:" in combined_compose
    assert "apps.classifier.shadow_worker" in combined_compose
    assert "PYTHONPATH=/app:/app/src" in combined_compose


def test_classifier_compose_mounts_shared_source_root_for_direct_ingestion():
    repo_root = Path(__file__).resolve().parents[1]
    classifier_compose = (repo_root / "deploy" / "roles" / "classifier" / "docker-compose.yml").read_text(encoding="utf-8")
    combined_compose = (repo_root / "deploy" / "roles" / "combined" / "docker-compose.yml").read_text(encoding="utf-8")

    assert "CLASSIFIER_SOURCE_ROOT=${CLASSIFIER_SOURCE_ROOT:-/source}" in classifier_compose
    assert "ICLOUD_MIRROR_ROOT=${ICLOUD_MIRROR_ROOT:-/srv/cloud-vault/mirrors}" in classifier_compose
    assert "CLASSIFIER_SOURCE_MOUNT_SOURCE" in classifier_compose
    assert "CLASSIFIER_SOURCE_ROOT=${CLASSIFIER_SOURCE_ROOT:-/source}" in combined_compose
    assert "ICLOUD_MIRROR_ROOT=${ICLOUD_MIRROR_ROOT:-/srv/cloud-vault/mirrors}" in combined_compose
    assert "CLASSIFIER_SOURCE_MOUNT_SOURCE" in combined_compose


def test_shadow_worker_compose_mounts_shared_source_root_for_image_reviews():
    repo_root = Path(__file__).resolve().parents[1]
    classifier_compose = (repo_root / "deploy" / "roles" / "classifier" / "docker-compose.yml").read_text(encoding="utf-8")
    combined_compose = (repo_root / "deploy" / "roles" / "combined" / "docker-compose.yml").read_text(encoding="utf-8")

    assert classifier_compose.count("CLASSIFIER_SOURCE_ROOT=${CLASSIFIER_SOURCE_ROOT:-/source}") >= 2
    assert classifier_compose.count("ICLOUD_MIRROR_ROOT=${ICLOUD_MIRROR_ROOT:-/srv/cloud-vault/mirrors}") >= 2
    assert classifier_compose.count("CLASSIFIER_SOURCE_MOUNT_SOURCE") >= 2
    assert combined_compose.count("CLASSIFIER_SOURCE_ROOT=${CLASSIFIER_SOURCE_ROOT:-/source}") >= 2
    assert combined_compose.count("ICLOUD_MIRROR_ROOT=${ICLOUD_MIRROR_ROOT:-/srv/cloud-vault/mirrors}") >= 2
    assert combined_compose.count("CLASSIFIER_SOURCE_MOUNT_SOURCE") >= 2
