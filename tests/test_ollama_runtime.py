from types import SimpleNamespace

import apps.classifier.ollama_runtime as ollama_runtime


def test_ensure_ollama_models_present_pulls_missing_models_once(monkeypatch):
    calls: list[str] = []
    seen_fetches = {"count": 0}

    def fake_fetch(_ollama_url: str, *, timeout: int = 5) -> set[str]:
        seen_fetches["count"] += 1
        if seen_fetches["count"] == 1:
            return {"qwen2.5vl:3b"}
        return {"qwen2.5:3b", "qwen2.5vl:3b"}

    def fake_pull(_ollama_url: str, model: str, *, timeout: int = 1800) -> None:
        calls.append(model)

    monkeypatch.setattr(ollama_runtime, "fetch_ollama_model_names", fake_fetch)
    monkeypatch.setattr(ollama_runtime, "pull_ollama_model", fake_pull)

    payload = ollama_runtime.ensure_ollama_models_present(
        "http://ollama:11434",
        required_models=["qwen2.5:3b", "qwen2.5vl:3b"],
        auto_pull_missing_models=True,
    )

    assert calls == ["qwen2.5:3b"]
    assert payload == {
        "available_models": ["qwen2.5:3b", "qwen2.5vl:3b"],
        "required_models": ["qwen2.5:3b", "qwen2.5vl:3b"],
        "missing_models": [],
        "pulled_models": ["qwen2.5:3b"],
        "required_models_present": True,
    }


def test_fetch_ollama_model_names_ignores_non_dict_items(monkeypatch):
    monkeypatch.setattr(
        ollama_runtime.requests,
        "get",
        lambda *_args, **_kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "models": [
                    {"name": "qwen2.5:3b"},
                    "junk",
                    {"name": " qwen2.5vl:3b "},
                    {},
                ]
            },
        ),
    )

    assert ollama_runtime.fetch_ollama_model_names("http://ollama:11434") == {
        "qwen2.5:3b",
        "qwen2.5vl:3b",
    }
