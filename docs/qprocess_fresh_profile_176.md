# QProcess-Bash: Standard mit frischem Profil prüfen

Für diesen Abnahmetest das **bestehende ShellDeck vollständig schließen**. Im Projektverzeichnis starten:

```bash
cd ~/Programme/visual-edit-terminal
.venv/bin/python tools/run_fresh_profile.py
```

Der Launcher erstellt nur für diesen Programmlauf eine temporäre HOME-/XDG-/APPDATA-Umgebung. Nach dem Beenden wird sie entfernt. Die normale Konfiguration wird nicht gelöscht oder geändert. Diese Isolierung gilt für die normale lokale Konfiguration; externe Dienste oder über andere Variablen ausdrücklich gewählte Datenverzeichnisse bleiben unberührt.

Unter Linux: `QProcess – kompatibel` als Engine wählen (die globale Engine-Auswahl bleibt unabhängig). Bei einer neuen Konfiguration sollte die Bash-Auswahl **„ohne Jobsteuerung“** anzeigen. Im Testprofil auf **„Bash: kompatibel“** wechseln, ein neues Terminal öffnen und den Rückfall testen; anschließend zurückwechseln. Mit `pwd`, `cd /tmp`, `pwd` und `echo OK` die Sitzung prüfen. Auch den Wechsel auf PTY/ConPTY und zurück prüfen.

**Wichtig:** Ein frisches Profil startet ohne deine normalen Tabs und gespeicherten Optionen. Das ist für den Test beabsichtigt. Der Produktionsmodus wird hierdurch nicht geändert. Nach erfolgreich abgeschlossener GUI-Prüfung trägt die freigegebene Auswahl kein „(Test)“-Etikett mehr.
