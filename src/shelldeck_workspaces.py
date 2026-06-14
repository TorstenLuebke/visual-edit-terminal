from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_workspace(value: Any) -> Dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    name = _clean_text(data.get("name")) or "Workspace"
    tabs = data.get("tabs", [])
    normalized_tabs: List[Dict[str, str]] = []
    if isinstance(tabs, list):
        for item in tabs:
            if not isinstance(item, dict):
                continue
            normalized_tabs.append({
                "shell_type": _clean_text(item.get("shell_type")) or "cmd",
                "title": _clean_text(item.get("title")),
                "working_directory": _clean_text(item.get("working_directory")),
                "command_history": [str(value or "").strip() for value in item.get("command_history", []) if str(value or "").strip()] if isinstance(item.get("command_history"), list) else [],
                "client_mode_kind": _clean_text(item.get("client_mode_kind") or item.get("client_mode")),
                "ollama_model": _clean_text(item.get("ollama_model")),
                "ollama_system_prompt": _clean_text(item.get("ollama_system_prompt")),
            })
    return {
        "name": name,
        "tabs": normalized_tabs,
        "default_start_directory": _clean_text(data.get("default_start_directory")),
        "selected_ollama_model": _clean_text(data.get("selected_ollama_model")),
        "shell_type": _clean_text(data.get("shell_type")) or "cmd",
    }


def normalize_workspaces(values: Any) -> List[Dict[str, Any]]:
    if not isinstance(values, list):
        return []
    result: List[Dict[str, Any]] = []
    seen = set()
    for value in values:
        workspace = normalize_workspace(value)
        key = workspace["name"].lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(workspace)
    return result


def workspace_from_tabs(
    tabs: Iterable[Dict[str, Any]],
    *,
    name: str,
    default_start_directory: str = "",
    selected_ollama_model: str = "",
    shell_type: str = "cmd",
) -> Dict[str, Any]:
    return normalize_workspace({
        "name": name,
        "tabs": list(tabs or []),
        "default_start_directory": default_start_directory,
        "selected_ollama_model": selected_ollama_model,
        "shell_type": shell_type,
    })


def workspace_display_label(workspace: Any) -> str:
    data = normalize_workspace(workspace)
    count = len(data.get("tabs", []))
    suffix = "Tab" if count == 1 else "Tabs"
    return f"{data['name']} ({count} {suffix})"
