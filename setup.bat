@echo off
chcp 65001 >nul
echo ============================================
echo   地理知识问答 RAG 系统 - 环境搭建
echo ============================================
echo.

cd /d "%~dp0"

echo [1/4] 创建 conda 环境...
conda create -n geo-rag python=3.10 -y
if errorlevel 1 (
    echo 错误: conda 环境创建失败
    pause
    exit /b 1
)

echo.
echo [2/4] 激活环境并安装依赖...
call conda activate geo-rag
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo 错误: 依赖安装失败
    pause
    exit /b 1
)

echo.
echo [3/4] 安装 llama-cpp-python (CUDA 版本)...
set CMAKE_ARGS="-DLLAMA_CUBLAS=on"
set FORCE_CMAKE=1
pip install llama-cpp-python --force-reinstall --no-deps -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo 警告: llama-cpp-python CUDA 版本安装失败，将使用 CPU 版本
)

echo.
echo [4/4] 创建必要目录...
if not exist "models" mkdir models
if not exist "data\documents" mkdir data\documents
if not exist "data\natural_earth" mkdir data\natural_earth

echo.
echo ============================================
echo   环境搭建完成！
echo.
echo   下一步:
echo   1. 下载模型文件到 models/ 目录:
echo      - Qwen2.5-7B-Instruct GGUF (约4.5GB)
echo        从 ModelScope 或 HuggingFace 下载
echo      - BGE-small-zh-v1.5 (约400MB)
echo        pip install modelscope
echo        modelscope download --model BAAI/bge-small-zh-v1.5 --local_dir models/bge-small-zh-v1.5
echo   2. 运行 run.bat 启动系统
echo ============================================
pause
