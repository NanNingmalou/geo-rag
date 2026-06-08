@echo off
cd /d "%~dp0"

set "PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4\bin;%PATH%"
set "PYTHON=C:\Users\znf\.conda\envs\geo-rag\python.exe"

if not exist "%PYTHON%" (
    echo Python not found: %PYTHON%
    pause
    exit /b 1
)

echo Starting RAG Geo Q&A...
echo Open http://localhost:8501 in browser
echo.

"%PYTHON%" -m streamlit run streamlit_app/main.py --server.port 8501

pause
