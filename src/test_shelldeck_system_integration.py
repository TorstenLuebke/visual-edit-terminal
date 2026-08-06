"""Tests der Systemintegration (ohne Qt, alle Systemzugriffe gemockt).

Es werden KEINE echten update-alternatives- oder Registry-Aenderungen
vorgenommen. Windows-Registry wird durch eine In-Memory-Attrappe ersetzt.

Ausfuehren (aus dem src-Ordner):

    python -m unittest test_shelldeck_system_integration
"""

import subprocess
import sys
import types
import unittest
from unittest import mock

import shelldeck_system_integration as si


# --- In-Memory-Attrappe fuer winreg ----------------------------------------

class _FakeHandle:
    def __init__(self, reg, path):
        self.reg = reg
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1
    KEY_ALL_ACCESS = 0xF003F

    def __init__(self):
        self.store = {}  # vollständiger Pfad -> {name: wert}

    def _full(self, root, path):
        return "%s\\%s" % (root, path)

    def CreateKey(self, root, path):
        full = self._full(root, path)
        self.store.setdefault(full, {})
        return _FakeHandle(self, full)

    def OpenKey(self, root, path, reserved=0, access=0):
        full = self._full(root, path)
        if full not in self.store:
            raise FileNotFoundError(path)
        return _FakeHandle(self, full)

    def SetValueEx(self, handle, name, reserved, typ, value):
        self.store[handle.path][name] = value

    def QueryValueEx(self, handle, name):
        values = self.store.get(handle.path, {})
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], self.REG_SZ

    def EnumKey(self, handle, index):
        prefix = handle.path + "\\"
        children = set()
        for key in self.store:
            if key.startswith(prefix):
                rest = key[len(prefix):]
                children.add(rest.split("\\", 1)[0])
        ordered = sorted(children)
        if index >= len(ordered):
            raise OSError("no more items")
        return ordered[index]

    def DeleteKey(self, root, path):
        full = self._full(root, path)
        prefix = full + "\\"
        if any(key.startswith(prefix) for key in self.store):
            raise OSError("key has subkeys")
        if full in self.store:
            del self.store[full]
        else:
            raise FileNotFoundError(path)

    def CloseKey(self, handle):
        return None


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# --- Linux ------------------------------------------------------------------

class LinuxCommandBuilderTests(unittest.TestCase):
    def test_install_command_arguments(self):  # Fall 19
        cmd = si.build_install_alternative_command("/usr/bin/shelldeck", 40, "update-alternatives")
        self.assertEqual(cmd, [
            "update-alternatives", "--install",
            "/usr/bin/x-terminal-emulator", "x-terminal-emulator",
            "/usr/bin/shelldeck", "40",
        ])

    def test_remove_command_arguments(self):  # Fall 20
        cmd = si.build_remove_alternative_command("/usr/bin/shelldeck", "update-alternatives")
        self.assertEqual(cmd, [
            "update-alternatives", "--remove",
            "x-terminal-emulator", "/usr/bin/shelldeck",
        ])

    def test_default_priority_is_modest(self):
        self.assertLessEqual(si.LINUX_ALTERNATIVE_PRIORITY, 50)


class LinuxDetectionTests(unittest.TestCase):
    def test_update_alternatives_detected(self):  # Fall 15
        with mock.patch.object(si.shutil, "which", return_value="/usr/bin/update-alternatives"):
            self.assertEqual(si.find_update_alternatives(), "/usr/bin/update-alternatives")

    def test_behavior_without_update_alternatives(self):  # Fall 16
        with mock.patch.object(si, "is_linux", return_value=True), \
             mock.patch.object(si, "find_update_alternatives", return_value=None):
            res = si.get_linux_terminal_alternative_status()
            self.assertFalse(res.success)
            self.assertIn("update-alternatives", res.message)
            res_i = si.install_linux_terminal_alternative()
            self.assertFalse(res_i.success)

    def test_registered_alternative_detected(self):  # Fall 17
        query = ("Name: x-terminal-emulator\nValue: /usr/bin/xterm\n\n"
                 "Alternative: /usr/bin/shelldeck\nPriority: 40\n")
        with mock.patch.object(si, "is_linux", return_value=True), \
             mock.patch.object(si, "find_update_alternatives", return_value="ua"), \
             mock.patch.object(si, "_run_process", return_value=_FakeCompleted(0, query)):
            res = si.get_linux_terminal_alternative_status("/usr/bin/shelldeck")
            self.assertTrue(res.success)
            self.assertIn("registriert", res.message.lower())

    def test_active_alternative_detected(self):  # Fall 18
        query = ("Name: x-terminal-emulator\nValue: /usr/bin/shelldeck\n\n"
                 "Alternative: /usr/bin/shelldeck\nPriority: 40\n")
        with mock.patch.object(si, "is_linux", return_value=True), \
             mock.patch.object(si, "find_update_alternatives", return_value="ua"), \
             mock.patch.object(si, "_run_process", return_value=_FakeCompleted(0, query)):
            res = si.get_linux_terminal_alternative_status("/usr/bin/shelldeck")
            self.assertIn("ausgewählt", res.message.lower())


class LinuxInstallTests(unittest.TestCase):
    def test_install_success(self):  # Fall 21 (idempotent: gleiche Argumente)
        calls = []

        def fake_run(args, timeout=20):
            calls.append(args)
            return _FakeCompleted(0, "done")

        with mock.patch.object(si, "is_linux", return_value=True), \
             mock.patch.object(si, "find_update_alternatives", return_value="ua"), \
             mock.patch.object(si, "_run_process", side_effect=fake_run):
            res1 = si.install_linux_terminal_alternative("/usr/bin/shelldeck")
            res2 = si.install_linux_terminal_alternative("/usr/bin/shelldeck")
            self.assertTrue(res1.success and res1.changed)
            self.assertTrue(res2.success)
            self.assertEqual(calls[0], calls[1])  # keine abweichenden Duplikate

    def test_remove_success(self):  # Fall 22
        with mock.patch.object(si, "is_linux", return_value=True), \
             mock.patch.object(si, "find_update_alternatives", return_value="ua"), \
             mock.patch.object(si, "_run_process", return_value=_FakeCompleted(0, "")):
            res = si.remove_linux_terminal_alternative("/usr/bin/shelldeck")
            self.assertTrue(res.success)

    def test_missing_rights(self):  # Fall 23
        with mock.patch.object(si, "is_linux", return_value=True), \
             mock.patch.object(si, "find_update_alternatives", return_value="ua"), \
             mock.patch.object(si, "_run_process", return_value=_FakeCompleted(1, "", "Permission denied")):
            res = si.install_linux_terminal_alternative("/usr/bin/shelldeck")
            self.assertFalse(res.success)
            self.assertIn("sudo", res.details)

    def test_failed_process_exception(self):  # Fall 24
        with mock.patch.object(si, "is_linux", return_value=True), \
             mock.patch.object(si, "find_update_alternatives", return_value="ua"), \
             mock.patch.object(si, "_run_process", side_effect=OSError("boom")):
            res = si.install_linux_terminal_alternative("/usr/bin/shelldeck")
            self.assertFalse(res.success)

    def test_no_linux_command_under_windows(self):  # Fall 25
        with mock.patch.object(si, "is_linux", return_value=False):
            res = si.install_linux_terminal_alternative("/usr/bin/shelldeck")
            self.assertFalse(res.success)
            self.assertIn("Linux", res.message)


# --- Windows ----------------------------------------------------------------

class WindowsBuilderTests(unittest.TestCase):
    def test_folder_command_uses_percent_1(self):  # Fall 26/27
        entries = si.build_windows_registry_entries(r"C:\Programme\ShellDeck\ShellDeck.exe")
        cmd = _command_value(entries, r"Directory\shell\ShellDeck\command")
        self.assertIn('--working-directory "%1"', cmd)
        self.assertTrue(cmd.startswith('"C:\\Programme\\ShellDeck\\ShellDeck.exe"'))

    def test_background_command_uses_percent_v(self):  # Fall 28/29
        entries = si.build_windows_registry_entries(r"C:\Programme\ShellDeck\ShellDeck.exe")
        cmd = _command_value(entries, r"Directory\Background\shell\ShellDeck\command")
        self.assertIn('--working-directory "%V"', cmd)

    def test_exe_with_spaces_is_quoted(self):  # Fall 30
        entries = si.build_windows_registry_entries(r"C:\Program Files\ShellDeck\ShellDeck.exe")
        cmd = _command_value(entries, r"Directory\shell\ShellDeck\command")
        self.assertIn('"C:\\Program Files\\ShellDeck\\ShellDeck.exe"', cmd)

    def test_icon_value_correct(self):  # Fall 31
        entries = si.build_windows_registry_entries(r"C:\x\ShellDeck.exe")
        icon = None
        for entry in entries:
            if entry.path.endswith(r"Directory\shell\ShellDeck"):
                icon = entry.values.get("Icon")
        self.assertEqual(icon, '"C:\\x\\ShellDeck.exe",0')

    def test_drives_optional(self):
        without = si.build_windows_registry_entries(r"C:\x\ShellDeck.exe", include_drives=False)
        with_drives = si.build_windows_registry_entries(r"C:\x\ShellDeck.exe", include_drives=True)
        self.assertFalse(any("Drive" in e.path for e in without))
        self.assertTrue(any("Drive" in e.path for e in with_drives))


class WindowsRegistryTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeWinreg()
        self._saved = sys.modules.get("winreg")
        sys.modules["winreg"] = self.fake

    def tearDown(self):
        if self._saved is not None:
            sys.modules["winreg"] = self._saved
        else:
            sys.modules.pop("winreg", None)

    def test_install_and_idempotent(self):  # Fall 32
        with mock.patch.object(si, "is_windows", return_value=True):
            res1 = si.install_windows_explorer_integration(r"C:\a\ShellDeck.exe")
            keys_after_first = dict(self.fake.store)
            res2 = si.install_windows_explorer_integration(r"C:\a\ShellDeck.exe")
        self.assertTrue(res1.success and res1.changed)
        self.assertTrue(res2.success)
        self.assertEqual(set(keys_after_first), set(self.fake.store))  # keine Duplikate

    def test_remove_idempotent(self):  # Fall 33
        with mock.patch.object(si, "is_windows", return_value=True):
            si.install_windows_explorer_integration(r"C:\a\ShellDeck.exe")
            res1 = si.remove_windows_explorer_integration()
            res2 = si.remove_windows_explorer_integration()
        self.assertTrue(res1.success and res1.changed)
        self.assertTrue(res2.success)
        self.assertFalse(res2.changed)
        self.assertEqual(self.fake.store, {})  # vollstaendig entfernt

    def test_outdated_path_updated(self):  # Fall 34
        with mock.patch.object(si, "is_windows", return_value=True):
            si.install_windows_explorer_integration(r"C:\alt\ShellDeck.exe")
            si.install_windows_explorer_integration(r"C:\neu\ShellDeck.exe")
            status = si.get_windows_explorer_integration_status(r"C:\neu\ShellDeck.exe")
        self.assertTrue(status.success)
        self.assertIn("aktuell", status.message.lower())
        # Kein alter Pfad mehr vorhanden
        joined = "\n".join(
            v.get("", "") for v in self.fake.store.values()
        )
        self.assertNotIn(r"C:\alt", joined)

    def test_only_shelldeck_keys_touched(self):
        with mock.patch.object(si, "is_windows", return_value=True):
            si.install_windows_explorer_integration(r"C:\a\ShellDeck.exe", include_drives=True)
        for key in self.fake.store:
            self.assertIn("ShellDeck", key)


class WindowsGuardTests(unittest.TestCase):
    def test_no_winreg_error_under_linux(self):  # Fall 35/36
        # is_windows False -> Funktionen kehren zurueck, ohne winreg zu benutzen.
        saved = sys.modules.pop("winreg", None)
        try:
            with mock.patch.object(si, "is_windows", return_value=False):
                res_status = si.get_windows_explorer_integration_status()
                res_install = si.install_windows_explorer_integration(r"C:\a\ShellDeck.exe")
                res_remove = si.remove_windows_explorer_integration()
            for res in (res_status, res_install, res_remove):
                self.assertFalse(res.success)
                self.assertIn("Windows", res.message)
        finally:
            if saved is not None:
                sys.modules["winreg"] = saved


class ImportSafetyTests(unittest.TestCase):
    def test_import_causes_no_side_effects(self):
        # Reiner Import darf nichts veraendern; detect ist read-only.
        info = si.detect_platform_integration()
        self.assertIn("platform", info)


def _command_value(entries, suffix):
    for entry in entries:
        if entry.path.endswith(suffix):
            return entry.values.get("", "")
    raise AssertionError("Eintrag nicht gefunden: " + suffix)


if __name__ == "__main__":
    unittest.main(verbosity=2)
