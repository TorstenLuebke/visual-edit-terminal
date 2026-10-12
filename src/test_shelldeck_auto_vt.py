"""Parser-Regressionen fuer den automatischen VT-Wechsel (ohne Qt)."""
import unittest
from shelldeck_auto_vt import direct_vt_program


class AutoVTCommandTests(unittest.TestCase):
    def test_supported_direct_commands(self):
        examples = {
            "vim /tmp/beispiel.txt": "vim",
            "nano text.txt": "nano",
            "htop": "htop",
            "/usr/bin/nvim +10 text.txt": "vim",
            "btop": "btop",
            "micro notiz.txt": "micro",
            "mc": "mc",
            "tmux new -s test": "tmux",
            "screen": "screen",
            "less 'datei mit leerzeichen.txt'": "less",
            "man bash": "man",
            "watch -n 2 date": "watch",
        }
        for command, expected in examples.items():
            with self.subTest(command=command):
                self.assertEqual(direct_vt_program(command), expected)

    def test_no_false_positive_or_noninteractive_version(self):
        for command in (
            "", "echo vim", "python -c 'print(\"vim\")'",
            "vim --version", "htop --help", "ls vim", "grep vim abc.txt",
            "vim x | cat", "vim a && echo ok", "nano file; echo ok",
            "ssh host vim", "sudo vim datei", "unknownprog", "vim \"oops",
            "vim file\nrm -rf /", "watch --help",
        ):
            with self.subTest(command=command):
                self.assertIsNone(direct_vt_program(command))
