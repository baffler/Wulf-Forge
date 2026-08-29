@echo off
REM Double-click this. It self-elevates (approve the UAC prompt), reads the
REM live wulfram2.exe player position, and writes tools\player_pos.txt.
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process -Verb RunAs -Wait -FilePath 'python' -ArgumentList '\"%~dp0read_player_pos.py\"'"
echo.
echo Done. Result written to tools\player_pos.txt
type "%~dp0player_pos.txt"
pause
