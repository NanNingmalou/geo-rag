"""系统设置 - 参数调节、状态面板"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import subprocess
import json
from pathlib import Path

from streamlit_app.shared import get_llm, get_retriever, get_active_llm, init_session
from core.indexer import index_exists, load_meta

init_session()

st.title("⚙️ 系统设置")

# === LLM 后端设置 ===
st.subheader("🧠 大模型设置")

col_backend, col_key = st.columns(2)

with col_backend:
    current_backend = st.session_state.get("llm_backend", "local")
    backend = st.selectbox(
        "模型后端",
        options=["local", "deepseek"],
        index=0 if current_backend == "local" else 1,
        format_func=lambda x: "本地 Qwen2.5-7B" if x == "local" else "DeepSeek API",
        help="切换本地模型与云端 API",
    )

with col_key:
    if backend == "deepseek":
        api_key = st.text_input(
            "DeepSeek API Key",
            type="password",
            value=st.session_state.get("ds_api_key", ""),
            placeholder="sk-...",
            help="仅保存在当前会话中，不写入磁盘",
        )
        st.session_state.ds_api_key = api_key

        if not api_key:
            st.warning("请输入 DeepSeek API Key")

if backend == "deepseek":
    col_model, col_temp = st.columns(2)
    with col_model:
        ds_model = st.selectbox(
            "DeepSeek 模型",
            options=["deepseek-chat", "deepseek-reasoner"],
            index=0 if st.session_state.get("ds_model") == "deepseek-chat" else 1,
            help="deepseek-chat: 通用对话 | deepseek-reasoner: 推理增强",
        )
        st.session_state.ds_model = ds_model

if st.button("💾 应用模型设置", type="primary"):
    st.session_state.llm_backend = backend
    if backend == "deepseek":
        if not st.session_state.get("ds_api_key"):
            st.error("请先输入 DeepSeek API Key")
        else:
            st.success(f"已切换到 DeepSeek API ({st.session_state.ds_model})")
    else:
        st.success("已切换到本地 Qwen2.5-7B 模型")

st.divider()

col1, col2 = st.columns(2)

# --- 检索设置 ---
with col1:
    st.subheader("🔍 检索设置")

    top_k = st.slider("检索片段数", 1, 15, st.session_state.get("retrieval_top_k", 2))
    threshold = st.slider("相似度阈值", 0.0, 1.0, st.session_state.get("retrieval_threshold", 0.6), step=0.05)
    quality_weight = st.slider("质量反馈权重", 0.0, 1.0,
                               st.session_state.get("retrieval_quality_weight", 0.5),
                               step=0.1,
                               help="0=关闭反馈（原始相似度排序），值越大自测结果对检索排序的影响越强")

    if st.button("💾 应用检索设置"):
        st.session_state.retrieval_top_k = top_k
        st.session_state.retrieval_threshold = threshold
        st.session_state.retrieval_quality_weight = quality_weight
        retriever = get_retriever()
        retriever.top_k = top_k
        retriever.threshold = threshold
        retriever.quality_weight = quality_weight
        st.success("已应用！")

# --- 系统状态 ---
with col2:
    st.subheader("📊 系统状态")

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            used, total = result.stdout.strip().split(", ")
            st.metric("GPU 显存", f"{int(used)} MB / {int(total)} MB",
                      delta=f"空闲 {int(total)-int(used)} MB")
    except Exception:
        st.caption("无法获取 GPU 信息")

    current_backend_label = "DeepSeek API" if st.session_state.get("llm_backend") == "deepseek" else "Qwen2.5-7B (本地)"
    st.write(f"**当前后端**: {current_backend_label}")

    if index_exists():
        node_ids = load_meta()
        index_size = Path("data/index.faiss").stat().st_size / (1024 * 1024)
        doc_count = len(set(Path("data/documents").glob("*")))
        st.metric("索引文档", f"{doc_count} 个")
        st.metric("向量总数", f"{len(node_ids)} 条")
        st.metric("索引大小", f"{index_size:.0f} MB")
    else:
        st.warning("尚未建立索引")

# --- 测试检索 ---
st.divider()
st.subheader("🧪 测试检索")

test_query = st.text_input("输入测试查询", placeholder="输入一个关键词测试检索效果...")

if test_query:
    retriever = get_retriever()
    nodes, scores = retriever.retrieve(test_query)

    if nodes:
        for i, (node, score) in enumerate(zip(nodes, scores)):
            fname = node.metadata.get("file_name", "未知") if hasattr(node, "metadata") else "未知"
            text = node.text[:300] if hasattr(node, "text") else str(node)[:300]
            st.info(f"**#{i+1}** [{fname}] 相关度 {score*100:.0f}%\n\n{text}")
    else:
        st.warning("未找到相关内容")

# --- 身份管理 ---
st.divider()
st.subheader("👥 身份管理")

from streamlit_app.shared import init_session, get_active_llm, get_retriever, is_teacher, render_profile_selector

# 确保 init_session 和 profiles 初始化
if "profiles" not in st.session_state:
    st.session_state.profiles = ["teacher"]

render_profile_selector()

if is_teacher():
    # 学生档案管理
    profiles = st.session_state.get("profiles", ["teacher"])
    students = [p for p in profiles if p != "teacher"]

    if students:
        st.write("**学生档案：**")
        for s in students:
            name = s.replace("student_", "")
            col_s1, col_s2 = st.columns([3, 1])
            with col_s1:
                st.write(f"🎓 {name}")
            with col_s2:
                if st.button("🗑️ 删除", key=f"del_student_{s}"):
                    profiles.remove(s)
                    st.session_state.profiles = profiles
                    if st.session_state.get("current_profile") == s:
                        st.session_state.current_profile = "teacher"
                    st.rerun()
    else:
        st.caption("暂无学生档案，请添加学生。")

    # 添加学生
    with st.form("add_student_form"):
        new_name = st.text_input("学生姓名", placeholder="输入姓名...")
        if st.form_submit_button("➕ 添加学生"):
            if new_name.strip():
                sid = f"student_{new_name.strip()}"
                if sid not in profiles:
                    profiles.append(sid)
                    st.session_state.profiles = profiles
                    st.success(f"已添加学生：{new_name.strip()}")
                    st.rerun()
                else:
                    st.warning("该学生已存在")
else:
    st.info("切换至教师身份以管理学生档案。")

# --- 模型路径 ---
st.divider()
st.subheader("🔧 模型路径")

st.code(f"""
LLM:     models/qwen2.5-7b-instruct-q4_k_m.gguf
Embed:   BAAI/bge-small-zh-v1.5
FAISS:   data/index.faiss
SQLite:  data/stats.db
""")
