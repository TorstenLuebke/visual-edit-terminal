from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


DEFAULT_MAX_FILE_BYTES = 200_000

_TEXT_EXTENSIONS = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".json": "json",
    ".md": "markdown",
    ".txt": "text",
    ".log": "text",
    ".csv": "csv",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".bat": "bat",
    ".cmd": "bat",
    ".ps1": "powershell",
    ".sh": "bash",
}


def detect_language_for_path(path: Any) -> str:
    suffix = Path(str(path or "")).suffix.lower()
    return _TEXT_EXTENSIONS.get(suffix, "text")


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "cp850", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_text_file_context(path: Any, *, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> Dict[str, Any]:
    file_path = Path(str(path or "")).expanduser()
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(str(file_path))

    size = file_path.stat().st_size
    if size > int(max_bytes):
        raise ValueError(
            f"Datei ist zu groß ({size} Bytes). Limit: {int(max_bytes)} Bytes."
        )

    raw = file_path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ValueError("Die Datei wirkt binär und wird nicht als Text angehängt.")

    text = _decode_text(raw).replace("\r\n", "\n").replace("\r", "\n")
    return {
        "name": file_path.name,
        "path": str(file_path),
        "size": size,
        "language": detect_language_for_path(file_path),
        "text": text,
    }


def build_file_context_block(file_context: Dict[str, Any]) -> str:
    name = str(file_context.get("name", "") or "Datei")
    path = str(file_context.get("path", "") or "")
    language = str(file_context.get("language", "text") or "text")
    text = str(file_context.get("text", "") or "")

    return (
        "\n\n---\n"
        "Angehängte Datei als Kontext:\n"
        f"Datei: {name}\n"
        f"Pfad: {path}\n\n"
        f"```{language}\n"
        f"{text}\n"
        "```\n"
        "---\n"
    )


def append_file_context_to_prompt(prompt: Any, file_context: Dict[str, Any]) -> str:
    base = str(prompt or "").strip()
    block = build_file_context_block(file_context)
    if base:
        return base + block
    return block.lstrip()
