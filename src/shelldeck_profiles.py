from pathlib import Path


KNOWN_PROFILE_SHELLS = {
    "cmd",
    "powershell",
    "pwsh",
    "git_bash",
    "wsl",
    "bash",
    "zsh",
    "fish",
    "sh",
}


def normalize_profile(profile):
    """Return a stable ShellDeck tab profile dictionary."""
    if not isinstance(profile, dict):
        profile = {}

    name = str(profile.get("name", "") or "").strip()
    shell_type = str(profile.get("shell_type", "cmd") or "cmd").strip()
    if shell_type not in KNOWN_PROFILE_SHELLS:
        shell_type = "cmd"

    title = str(profile.get("title", "") or "").strip()
    working_directory = str(profile.get("working_directory", "") or "").strip().strip('"')
    startup_command = str(profile.get("startup_command", "") or "").strip()
    client_mode = str(profile.get("client_mode", "") or "").strip()
    ollama_model = str(profile.get("ollama_model", "") or "").strip()

    if not name:
        name = title or ollama_model or Path(working_directory).name or shell_type or "Profil"

    return {
        "name": name,
        "shell_type": shell_type,
        "title": title,
        "working_directory": working_directory,
        "startup_command": startup_command,
        "client_mode": client_mode,
        "ollama_model": ollama_model,
    }


def normalize_profiles(profiles):
    """Normalize, de-duplicate and sort profiles by insertion order."""
    result = []
    seen = set()
    if not isinstance(profiles, list):
        return result

    for item in profiles:
        profile = normalize_profile(item)
        key = profile["name"].strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(profile)

    return result


def profile_display_label(profile):
    profile = normalize_profile(profile)
    parts = [profile["name"]]
    details = []

    if profile["shell_type"]:
        details.append(profile["shell_type"])
    if profile["working_directory"]:
        details.append(profile["working_directory"])
    if profile["ollama_model"]:
        details.append(f"Ollama: {profile['ollama_model']}")
    if profile["startup_command"]:
        details.append("Startbefehl")

    if details:
        parts.append(" — " + " | ".join(details))
    return "".join(parts)


def profile_from_tab(tab, *, name="", startup_command=""):
    """Create a profile dictionary from a TerminalTab-like object."""
    shell_type = str(getattr(tab, "shell_type", "") or "cmd").strip()
    title = str(getattr(tab, "custom_title", "") or getattr(tab, "title", "") or "").strip()

    working_directory = ""
    refresh = getattr(tab, "refresh_current_working_directory", None)
    if callable(refresh):
        try:
            working_directory = str(refresh() or "").strip()
        except Exception:
            working_directory = ""
    if not working_directory:
        working_directory = str(getattr(tab, "current_working_directory", "") or "").strip()

    client_mode = str(getattr(tab, "client_mode_kind", "") or "").strip()
    ollama_model = str(getattr(tab, "ollama_model", "") or "").strip()

    return normalize_profile({
        "name": name or title or Path(working_directory).name or shell_type or "Profil",
        "shell_type": shell_type,
        "title": title,
        "working_directory": working_directory,
        "startup_command": startup_command,
        "client_mode": client_mode,
        "ollama_model": ollama_model,
    })
