"""地理知识问答 RAG 系统 - 入口"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

st.set_page_config(
    page_title="地理知识问答 RAG",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

from streamlit_app.shared import init_session, render_profile_selector
init_session()
render_profile_selector()

st.title("🌍 地理知识问答 RAG 系统")

st.markdown("""
### 欢迎使用

本系统基于 **RAG（检索增强生成）** 技术，为高中地理教学提供智能化支持。

请从左侧边栏选择功能页面开始使用。
""")
