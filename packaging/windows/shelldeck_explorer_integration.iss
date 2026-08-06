; ShellDeck - Explorer-Integration (Include fuer das Inno-Setup-Hauptskript)
;
; Einbinden im Haupt-Setup ueber:
;     #include "shelldeck_explorer_integration.iss"
;
; Erwartet, dass das Haupt-Setup die Programmdatei {app}\ShellDeck.exe
; installiert. Es werden ausschliesslich benutzerbezogene Schluessel unter
; HKCU\Software\Classes gesetzt - keine systemweite HKLM-Aenderung.
;
; Der Eintrag "In ShellDeck oeffnen" erscheint unter Windows 11 ggf. erst
; unter "Weitere Optionen anzeigen". ShellDeck wird dadurch NICHT zum nativen
; Windows-Standard-Terminalhost (siehe Projektdokumentation).

[Tasks]
Name: "shelldeck_explorer"; Description: "&In ShellDeck oeffnen zum Explorer-Kontextmenue hinzufuegen"; GroupDescription: "Explorer-Integration:"; Flags: unchecked
Name: "shelldeck_explorer_drives"; Description: "Auch fuer Laufwerke anzeigen"; GroupDescription: "Explorer-Integration:"; Flags: unchecked

[Registry]
; --- Ordner (Rechtsklick auf einen Ordner) -> %1 ist der Ordnerpfad ---
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ShellDeck"; ValueType: string; ValueData: "In ShellDeck oeffnen"; Flags: uninsdeletekey; Tasks: shelldeck_explorer
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ShellDeck"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\ShellDeck.exe"",0"; Tasks: shelldeck_explorer
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ShellDeck\command"; ValueType: string; ValueData: """{app}\ShellDeck.exe"" --working-directory ""%1"""; Tasks: shelldeck_explorer

; --- Ordnerhintergrund (Rechtsklick in den freien Bereich) -> %V ---
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\ShellDeck"; ValueType: string; ValueData: "In ShellDeck oeffnen"; Flags: uninsdeletekey; Tasks: shelldeck_explorer
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\ShellDeck"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\ShellDeck.exe"",0"; Tasks: shelldeck_explorer
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\ShellDeck\command"; ValueType: string; ValueData: """{app}\ShellDeck.exe"" --working-directory ""%V"""; Tasks: shelldeck_explorer

; --- Laufwerke (optional) -> %V ist der Laufwerksstamm ---
Root: HKCU; Subkey: "Software\Classes\Drive\shell\ShellDeck"; ValueType: string; ValueData: "In ShellDeck oeffnen"; Flags: uninsdeletekey; Tasks: shelldeck_explorer_drives
Root: HKCU; Subkey: "Software\Classes\Drive\shell\ShellDeck"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\ShellDeck.exe"",0"; Tasks: shelldeck_explorer_drives
Root: HKCU; Subkey: "Software\Classes\Drive\shell\ShellDeck\command"; ValueType: string; ValueData: """{app}\ShellDeck.exe"" --working-directory ""%V"""; Tasks: shelldeck_explorer_drives
