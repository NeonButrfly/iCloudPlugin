from pathlib import Path


def test_classifier_dockerfile_copies_shared_packages_for_monorepo_runtime():
    repo_root = Path(__file__).resolve().parents[1]
    dockerfile = repo_root / "apps" / "classifier" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "COPY packages /app/packages" in text


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
    assert "paddlepaddle" in dockerfile
