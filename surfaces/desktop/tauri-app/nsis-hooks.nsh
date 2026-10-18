; Installer hooks for the full HelmDeck install (the Tauri twin of the Electron NSIS installer).
; The window is not the supervisor: helmdeck-tray.exe is. It starts and watches the daemon (from the
; daemon/ sources installed next to it), runs the relay bridge when relay.engine is "pipe", and is what
; brings the daemon back after a reboot - so the installer registers it for login and starts it once.
;
; Two traps measured on 2026-10-18 with the first build of this file:
; * Tauri's per-user default folder is %LOCALAPPDATA%\HelmDeck - the folder HelmDeck already uses for its
;   browser profiles (chrome-profile, chrome-atlassian) and the tray copy. Tauri's uninstaller only deletes
;   its own files and EMPTY folders (installer.nsi: RMDir without /r), so the profiles were never at risk,
;   but program and data do not belong in one folder: the program goes to %LOCALAPPDATA%\Programs\HelmDeck
;   (the Windows convention for per-user programs).
; * `taskkill /IM helmdeck-tray.exe` stopped EVERY tray and bridge on the machine, including one from a
;   different install - the phone lost the desktop for minutes. Only processes running FROM $INSTDIR are
;   stopped now.

!define HD_RUN_KEY "Software\Microsoft\Windows\CurrentVersion\Run"

!macro HD_STOP_OURS
  ; stop helmdeck-tray / helmdeck-relay-bridge processes whose exe lives in $INSTDIR - nothing else
  nsExec::Exec `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "Get-Process helmdeck-tray,helmdeck-relay-bridge -ErrorAction SilentlyContinue | Where-Object { $$_.Path -and $$_.Path.StartsWith('$INSTDIR\', [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force"`
  Pop $0
!macroend

!macro NSIS_HOOK_PREINSTALL
  ; never install into the folder that holds HelmDeck's browser profiles (see above)
  ; (Tauri's template already ran `SetOutPath $INSTDIR` before this hook - without re-setting it the files
  ; would still go to the old folder while only the empty resource folders land in the new one)
  StrCmp $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}" 0 +3
    StrCpy $INSTDIR "$LOCALAPPDATA\Programs\${PRODUCTNAME}"
    SetOutPath $INSTDIR
  ; an update replaces these exes, so OUR copies must not be running (the daemon is left alone: the new
  ; tray adopts it by health, exactly as on a normal start)
  !insertmacro HD_STOP_OURS
!macroend

!macro NSIS_HOOK_POSTINSTALL
  WriteRegStr HKCU "${HD_RUN_KEY}" "HelmDeck" '"$INSTDIR\helmdeck-tray.exe" --root "$INSTDIR"'
  Exec '"$INSTDIR\helmdeck-tray.exe" --root "$INSTDIR"'
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro HD_STOP_OURS
  ; only remove the autostart if it is OURS (another install may own the value)
  ReadRegStr $1 HKCU "${HD_RUN_KEY}" "HelmDeck"
  StrCmp $1 '"$INSTDIR\helmdeck-tray.exe" --root "$INSTDIR"' 0 +2
    DeleteRegValue HKCU "${HD_RUN_KEY}" "HelmDeck"
!macroend
