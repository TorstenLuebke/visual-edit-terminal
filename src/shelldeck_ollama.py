from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/generate"


def clean_model_name(value: Any) -> str:
    return str(value or "").strip()


def normalize_system_prompt(value: Any) -> str:
    return str(value or "").strip()


def build_generate_payload(
    model: str,
    prompt: str,
    *,
    context: Optional[List[int]] = None,
    system_prompt: str = "",
    stream: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": clean_model_name(model),
        "prompt": str(prompt or ""),
        "stream": bool(stream),
    }
    if isinstance(context, list) and context:
        payload["context"] = context
    system = normalize_system_prompt(system_prompt)
    if system:
        payload["system"] = system
    return payload


def extract_generate_response(raw: str) -> Tuple[str, Optional[List[int]]]:
    result = json.loads(str(raw or "{}"))
    if "error" in result:
        raise RuntimeError(str(result.get("error") or "Unbekannter Ollama-Fehler"))
    answer = str(result.get("response", "") or "")
    context = result.get("context")
    return answer, context if isinstance(context, list) else None


def ollama_api_error_message(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError):
        return (
            "Ollama ist nicht erreichbar. Prüfe, ob Ollama läuft "
            "(normalerweise http://127.0.0.1:11434). Details: "
            f"{exc}"
        )
    return f"Ollama-API-Fehler: {exc}"


def list_ollama_models(timeout: int = 8) -> List[str]:
    executable = shutil.which("ollama")
    if not executable:
        return []
    try:
        result = subprocess.run(
            [executable, "list"],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return []

    models: List[str] = []
    for line in (result.stdout or "").splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def markdown_chat_export(*, app_name: str, model: str, system_prompt: str, transcript: str) -> str:
    lines = [f"# {app_name} Ollama-Chat", ""]
    if model:
        lines.extend([f"**Modell:** `{model}`", ""])
    if system_prompt:
        lines.extend(["## Systemprompt", "", system_prompt.strip(), ""])
    lines.extend(["## Verlauf", "", str(transcript or "").strip(), ""])
    return "\n".join(lines).replace("\r\n", "\n").replace("\r", "\n")
