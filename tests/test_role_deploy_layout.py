from pathlib import Path


def test_role_docs_exist_for_cloudsync_classifier_and_combined():
    repo_root = Path(__file__).resolve().parents[1]
    expected = [
        repo_root / "deploy" / "roles" / "cloudsync" / "README.md",
        repo_root / "deploy" / "roles" / "classifier" / "README.md",
        repo_root / "deploy" / "roles" / "combined" / "README.md",
    ]

    assert all(path.exists() for path in expected)
