from __future__ import annotations

import html
import re
from typing import Any, Dict, List


_CODE_FENCE_RE = re.compile(r"```([A-Za-z0-9_+.#-]*)\s*\n(.*?)```", re.DOTALL)


def normalize_language(value: Any) -> str:
    """Return a compact display label for a Markdown code fence language."""
    text = str(value or "").strip().lower()
    aliases = {
        "ps1": "PowerShell",
        "powershell": "PowerShell",
        "pwsh": "PowerShell",
        "py": "Python",
        "python": "Python",
        "js": "JavaScript",
        "javascript": "JavaScript",
        "ts": "TypeScript",
        "typescript": "TypeScript",
        "sql": "SQL",
        "bash": "Bash",
        "sh": "Shell",
        "shell": "Shell",
        "cmd": "CMD",
        "bat": "Batch",
        "json": "JSON",
        "yaml": "YAML",
        "yml": "YAML",
        "html": "HTML",
        "css": "CSS",
        "diff": "Diff",
        "patch": "Patch",
        "text": "Text",
    }
    return aliases.get(text, text.upper() if text else "Code")


def extract_code_blocks(markdown_text: Any) -> List[Dict[str, str]]:
    """Extract fenced Markdown code blocks from text."""
    text = str(markdown_text or "")
    blocks: List[Dict[str, str]] = []
    for match in _CODE_FENCE_RE.finditer(text):
        language = normalize_language(match.group(1))
        code = str(match.group(2) or "").strip("\n")
        if code.strip():
            blocks.append({"language": language, "code": code})
    return blocks


def _paragraph_html(text: str) -> str:
    escaped = html.escape(text).replace("\r\n", "\n").replace("\r", "\n")
    return escaped.replace("\n", "<br>")


def markdown_to_html(markdown_text: Any) -> str:
    """Render a small safe Markdown subset for QTextEdit.

    The renderer is intentionally conservative: normal text is escaped and
    fenced code blocks are shown as visually separated cards.
    """
    text = str(markdown_text or "")
    parts: List[str] = []
    last = 0

    code_index = 0
    for match in _CODE_FENCE_RE.finditer(text):
        before = text[last:match.start()]
        if before.strip():
            parts.append(f"<p style='margin:6px 0;'>{_paragraph_html(before.strip())}</p>")

        language = normalize_language(match.group(1))
        code = str(match.group(2) or "").strip("\n")
        safe_code = html.escape(code)
        safe_language = html.escape(language)
        copy_href = f"shelldeck-copy-code:{code_index}"
        parts.append(
            "<div style='margin:10px 0; border:1px solid #334155; "
            "border-radius:9px; background-color:#0F172A;'>"
            "<div style='padding:7px 10px; background-color:#1E293B; "
            "color:#E5E7EB; font-weight:bold;'>"
            f"<span>{safe_language}</span>"
            f"<a href='{copy_href}' style='float:right; color:#93C5FD; "
            "text-decoration:none; font-weight:bold;'>Kopieren</a>"
            "</div>"
            "<pre style='margin:0; padding:12px; color:#F8FAFC; "
            "font-family:Consolas, Courier New, monospace; font-size:10pt; "
            "line-height:1.25; white-space:pre-wrap;'>"
            f"{safe_code}"
            "</pre>"
            "</div>"
        )
        code_index += 1
        last = match.end()

    rest = text[last:]
    if rest.strip():
        parts.append(f"<p style='margin:6px 0;'>{_paragraph_html(rest.strip())}</p>")

    if not parts:
        return ""
    return "".join(parts)


def ollama_answer_to_html(answer: Any) -> str:
    body = markdown_to_html(answer)
    if not body:
        return ""
    return (
        "<div style='margin-top:10px; margin-bottom:6px;'>"
        "<b>Ollama →</b>"
        "</div>"
        f"{body}"
        "<div style='height:8px;'></div>"
    )
