from __future__ import annotations

import time
from typing import Any

import requests


def fetch_ollama_model_names(ollama_url: str, *, timeout: int = 5) -> set[str]:
    response = requests.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    models = payload.get("models", []) if isinstance(payload, dict) else []
    names: set[str] = set()
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        if name:
            names.add(name)
    return names


def pull_ollama_model(ollama_url: str, model: str, *, timeout: int = 1800) -> None:
    response = requests.post(
        f"{ollama_url.rstrip('/')}/api/pull",
        json={"name": model, "stream": False},
        timeout=timeout,
    )
    response.raise_for_status()


def ensure_ollama_models_present(
    ollama_url: str,
    *,
    required_models: list[str],
    auto_pull_missing_models: bool = True,
    pull_timeout: int = 1800,
) -> dict[str, Any]:
    available = fetch_ollama_model_names(ollama_url)
    required = [str(model).strip() for model in required_models if str(model).strip()]
    missing = [model for model in required if model not in available]
    pulled: list[str] = []

    if missing and auto_pull_missing_models:
        for model in missing:
            pull_ollama_model(ollama_url, model, timeout=pull_timeout)
            pulled.append(model)
        available = fetch_ollama_model_names(ollama_url)
        missing = [model for model in required if model not in available]

    return {
        "available_models": sorted(available),
        "required_models": required,
        "missing_models": missing,
        "pulled_models": pulled,
        "required_models_present": not missing,
    }


def wait_for_ollama(
    ollama_url: str,
    *,
    timeout_seconds: int = 120,
    required_models: list[str] | None = None,
    auto_pull_missing_models: bool = True,
) -> None:
    deadline = time.time() + timeout_seconds
    last_error = None
    attempted_pull = False

    while time.time() < deadline:
        try:
            model_status = ensure_ollama_models_present(
                ollama_url,
                required_models=list(required_models or []),
                auto_pull_missing_models=auto_pull_missing_models and not attempted_pull,
            )
            if model_status["required_models_present"]:
                return
            attempted_pull = attempted_pull or bool(model_status["pulled_models"])
            last_error = (
                "missing required Ollama models: "
                + ", ".join(model_status["missing_models"])
            )
        except Exception as exc:
            last_error = str(exc)

        time.sleep(2)

    raise RuntimeError(f"Ollama did not become ready at {ollama_url}: {last_error}")
