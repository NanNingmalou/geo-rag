# 基于 RAG 的高中地理知识问答系统

利用检索增强生成（RAG）技术，将高中地理教材内容构建为本地知识库，实现AI精准问答、自测练习、学情分析的学习辅助系统。

## 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 |
| GPU | NVIDIA RTX 3060 及以上（8GB 显存） |
| CUDA | 12.4 |
| Python | 3.10 |
| 包管理 | Anaconda / Miniconda |

> 没有 NVIDIA 显卡可以改用 CPU 推理（修改 `setup.bat`，去掉第32行 `-DLLAMA_CUBLAS=on`）。

## 快速开始

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd rag
```

### 2. 一键搭建环境

```bash
setup.bat
```

这一步会：创建 conda 虚拟环境 → 安装 Python 依赖 → 编译 CUDA 版 llama-cpp → 创建数据目录。

### 3. 下载模型文件

```bash
conda activate geo-rag

# BGE Embedding 模型（约400MB）
pip install modelscope
modelscope download --model BAAI/bge-small-zh-v1.5 --local_dir models/bge-small-zh-v1.5

# Qwen2.5-7B GGUF 量化模型（约4.5GB）
# 从 ModelScope 或 HuggingFace 下载 qwen2.5-7b-instruct-q4_k_m.gguf
# 放到 models/ 目录下
```

### 4. 准备教材文档

将高中地理教材 PDF 或 DOCX 文件放入 `data/documents/` 目录。系统支持一次上传多个文件。

### 5. 启动系统

```bash
run.bat
```

浏览器打开 `http://localhost:8501`，进入「知识库管理」页面上传文档并构建索引。

## 系统功能介绍

8 个功能页面，覆盖完整学习闭环：

| 页面 | 功能 |
|------|------|
| 学情仪表盘 | 掌握度总览、趋势图、薄弱点分析 |
| 知识库管理 | 教材上传、自动分块、向量索引构建 |
| 智能问答 | RAG 对话，回答锚定教材原文 + 精确页码 |
| 自测练习 | 热度/题库/错题三种模式自动出题 |
| 错题本 | 错题回顾、重测、标记已掌握 |
| 知识点管理 | 4域20章100知识点目录浏览、分类回填 |
| 题库管理 | 教师自定义题目（支持 CSV 导入） |
| 学习计划 | LLM 根据薄弱点生成结构化复习计划 |

## 项目结构

```
├── core/               # RAG 核心引擎
│   ├── llm.py          # LLM 推理（Qwen 本地 + DeepSeek API 双后端）
│   ├── embedder.py     # BGE 向量化
│   ├── loader.py       # 文档加载
│   ├── splitter.py     # 文本分块
│   ├── indexer.py      # FAISS 索引构建
│   └── retriever.py    # 向量检索
├── utils/              # 业务逻辑
│   ├── db.py           # SQLite 数据库
│   ├── knowledge_points.py  # 知识点分类与掌握度计算
│   ├── quiz.py         # 自测引擎
│   └── report_generator.py  # Word 学习报告生成
├── streamlit_app/      # Web UI（Streamlit 多页应用）
│   ├── main.py         # 首页
│   └── pages/          # 8 个功能页面
├── data/
│   └── knowledge_taxonomy.json  # 知识点分类体系（4域20章100知识点）
├── setup.bat           # 环境搭建脚本
├── run.bat             # 启动脚本
└── requirements.txt    # Python 依赖
```

## 配置说明

系统默认使用本地 Qwen2.5-7B 模型。如需切换为 DeepSeek API：

1. 在「系统设置」页面切换 LLM 后端为 DeepSeek
2. 设置环境变量 `DEEPSEEK_API_KEY=你的key`

修改 `.streamlit/config.toml` 可调整 Streamlit 服务器端口等参数。

## 注意事项

- 首次启动需要构建 FAISS 索引，根据文档数量可能需要几分钟
- 知识点分类功能需要先运行「数据回填」（在知识点管理页面操作）
- 索引文件和数据库存储在 `data/` 目录，备份时保留此目录即可
