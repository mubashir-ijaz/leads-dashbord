@echo off
REM Starts YOUR normal Chrome with a debugging port so instagram_dm.py --attach
REM can drive it (uses your existing Instagram login - no fresh login needed).
REM
REM 1. Close ALL other Chrome windows first.
REM 2. Double-click this file.
REM 3. In another terminal:  python instagram_dm.py --attach

set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

start "" %CHROME% --remote-debugging-port=9223 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data" --profile-directory=Default
