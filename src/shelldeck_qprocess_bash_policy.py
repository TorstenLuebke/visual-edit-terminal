"""Konservative Auswahl fuer das QProcess-Bash-Abschlussprotokoll.

Nur Befehle, deren stdin nicht an interaktive Anwendungen abgegeben werden
kann, duerfen unmittelbar mit einem Abschlussmarker verkettet werden.
Unbekannte Syntax bleibt auf dem bisherigen Befehlsweg.
"""
import re
import shlex

_INTERACTIVE = frozenset({
    'sudo', 'su', 'ssh', 'scp', 'sftp', 'passwd', 'read', 'select',
    'python', 'python3', 'ipython', 'node', 'ruby', 'irb', 'lua',
    'vim', 'vi', 'nano', 'emacs', 'less', 'more', 'man', 'top', 'htop',
    'bash', 'sh', 'zsh', 'fish', 'tmux', 'screen', 'ftp', 'telnet',
    'mysql', 'psql', 'sqlite3', 'gdb', 'lldb', 'watch',
})
_SAFE_BUILTINS = frozenset({'cd', 'pwd', 'export', 'unset', 'true', 'false',
                           'echo', 'printf', 'type', 'command', 'alias',
                           'unalias', 'deactivate', 'source', '.'})


def command_allows_completion_marker(command):
    """Nur bekannte einfache Shell-Befehle freigeben (fail closed).

    Dies ist *keine* Shell-Syntaxvalidierung und keine Sicherheits-Sandbox.
    Es verhindert lediglich, dass Marker blind an interaktive Clients gehen.
    """
    value = str(command or '').strip()
    if not value or '\n' in value or '\r' in value or '\x00' in value:
        return False
    if re.search(r'[;&|<>`\\()]|\$\(|\$\{|\b(?:exec|eval|trap|function)\b', value):
        return False
    try:
        words = shlex.split(value, posix=True)
    except ValueError:
        return False
    if not words:
        return False
    # Escaped line breaks can hide further shell statements.  Likewise,
    # hash comments should not be permitted to alter command boundaries.
    if '# ' in value or value.endswith('#'):
        return False
    first = words[0]
    # An assignment prefix or a control keyword changes Bash parsing and
    # can turn following text into an arbitrary command.
    if re.match(r'^[A-Za-z_][A-Za-z_0-9]*=', first):
        return False
    if first in {'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until', 'do', 'done', 'case', 'esac'}:
        return False
    if first in _INTERACTIVE or first in {'builtin', 'env'}:
        return False
    # Externe Programme koennen unabhaengig vom Namen stdin lesen.
    if first not in _SAFE_BUILTINS:
        return False
    if first in {'source', '.'}:
        # Beliebige gesourcte Skripte koennen stdin konsumieren.
        return False
    return True
