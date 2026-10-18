"""Prueft, ob ein wiederherzustellendes venv bereits vom PTY geerbt wurde."""
from pathlib import Path


def inherited_venv_already_active(target_venv, inherited_venv):
    """Nur dieselbe existierende Umgebung darf erneutem `activate` vorgehen."""
    if not target_venv or not inherited_venv:
        return False
    try:
        target = Path(target_venv).expanduser().resolve(strict=True)
        inherited = Path(inherited_venv).expanduser().resolve(strict=True)
        return target.is_dir() and inherited.is_dir() and target == inherited
    except (OSError, RuntimeError, ValueError):
        return False
