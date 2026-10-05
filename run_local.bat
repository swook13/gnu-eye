@echo off
rem GNU-Eye v2: run on this PC with local Ollama (qwen2.5:7b)
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
rem Python: project .venv first, then the team laptop venv, then python on PATH
set PY=python
if exist "..\projects\.venv\Scripts\python.exe" set PY=..\projects\.venv\Scripts\python.exe
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if "%OLLAMA_HOST%"=="" set OLLAMA_HOST=http://localhost:11434
if "%GNUEYE_MODEL%"=="" set GNUEYE_MODEL=qwen2.5:7b
echo LLM: %OLLAMA_HOST%  model: %GNUEYE_MODEL%
echo Open http://localhost:8000
"%PY%" -m uvicorn api.main:app --port 8000
