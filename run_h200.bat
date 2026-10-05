@echo off
rem GNU-Eye v2: web/API on this laptop, LLM on the GNU H200 server (team Ollama, port 11525) through an SSH tunnel
rem Needs an SSH host alias "GNU_server" in ~/.ssh/config. Other setups: use run_local.bat with OLLAMA_HOST.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PY=python
if exist "..\projects\.venv\Scripts\python.exe" set PY=..\projects\.venv\Scripts\python.exe
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
echo Starting Ollama on the server if it is not running...
ssh -o BatchMode=yes GNU_server "~/ollama/start.sh"
echo Opening SSH tunnel localhost:11525 ...
start "gnu-eye-tunnel" /min ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -N -L 11525:127.0.0.1:11525 GNU_server
timeout /t 4 /nobreak >nul
set OLLAMA_HOST=http://localhost:11525
if "%GNUEYE_MODEL%"=="" set GNUEYE_MODEL=qwen2.5:14b
echo LLM: %OLLAMA_HOST%  model: %GNUEYE_MODEL%
echo Open http://localhost:8000
"%PY%" -m uvicorn api.main:app --port 8000
