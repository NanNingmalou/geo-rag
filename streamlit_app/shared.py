"""共享资源 - LLM / Embedder / Retriever 单例"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st


@st.cache_resource
def get_embedder():
    from core.embedder import Embedder
    return Embedder()  # auto-detect cuda/cpu


@st.cache_resource
def get_llm():
    """本地 Qwen 模型（缓存单例）"""
    from core.llm import LLM
    return LLM(model_path="models/qwen2.5-7b-instruct-q4_k_m.gguf")


def get_deepseek_llm():
    """DeepSeek API 实例（不缓存，每次从 session state 读取 api_key）"""
    from core.llm import DeepSeekLLM
    api_key = st.session_state.get("ds_api_key", "")
    model = st.session_state.get("ds_model", "deepseek-chat")
    if not api_key:
        return None
    return DeepSeekLLM(api_key=api_key, model=model)


def get_active_llm():
    """根据当前设置返回活跃的 LLM 实例"""
    backend = st.session_state.get("llm_backend", "local")
    if backend == "deepseek":
        return get_deepseek_llm()
    return get_llm()


@st.cache_resource
def get_retriever():
    from core.retriever import Retriever
    from utils.db import init_db

    init_db()
    embedder = get_embedder()
    retriever = Retriever(embedder, quality_weight=st.session_state.get("retrieval_quality_weight", 0.5))
    return retriever


def init_session():
    """初始化 session state 默认值 + 自动同步知识点分类目录"""
    defaults = {
        "messages": [],
        "retrieval_top_k": 2,
        "retrieval_threshold": 0.6,
        "quiz_mode": "top",
        "quiz_count": 10,
        "llm_backend": "local",
        "ds_api_key": "",
        "ds_model": "deepseek-chat",
        "retrieval_quality_weight": 0.5,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # 自动同步知识点分类目录到数据库（首次启动时）
    if "kp_taxonomy_synced" not in st.session_state:
        try:
            from utils.knowledge_points import sync_taxonomy_to_db
            count = sync_taxonomy_to_db()
            st.session_state.kp_taxonomy_synced = True
        except Exception:
            pass


def get_current_profile():
    """获取当前活跃的 profile_id"""
    import streamlit as st
    return st.session_state.get("current_profile", "teacher")


def get_profile_filter():
    """返回当前 profile 的 SQL 过滤条件。teacher 返回 None（不过滤）。"""
    profile = st.session_state.get("current_profile", "teacher") if _st_available() else "teacher"
    if profile == "teacher":
        return None
    return profile


def is_teacher():
    """当前是否为教师身份"""
    return st.session_state.get("current_profile", "teacher") == "teacher"


def _st_available():
    """检查 streamlit 上下文是否可用"""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


def render_profile_selector():
    """在侧边栏渲染身份选择器"""
    import streamlit as st

    profiles = st.session_state.get("profiles", ["teacher"])
    current = st.session_state.get("current_profile", "teacher")

    with st.sidebar:
        st.divider()
        selected = st.selectbox(
            "👤 当前身份",
            profiles,
            index=profiles.index(current) if current in profiles else 0,
            format_func=lambda x: "🧑‍🏫 教师" if x == "teacher" else f"🎓 {x.replace('student_', '')}",
        )
        if selected != current:
            st.session_state.current_profile = selected
            st.rerun()
