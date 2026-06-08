"""智能问答 - 核心对话页"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from streamlit_app.shared import get_active_llm, get_retriever, init_session, get_current_profile, render_profile_selector
from utils.db import log_question

init_session()
render_profile_selector()

st.title("💬 地理知识问答")

# 清除对话按钮
if st.button("🗑️ 清除对话"):
    st.session_state.messages = []
    st.rerun()

chat_container = st.container()

# 渲染历史
with chat_container:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources"):
                with st.expander("📚 参考来源"):
                    for i, src in enumerate(msg["sources"]):
                        fname = src.get("file_name", "未知")
                        score = src.get("score", 0) * 100
                        page = src.get("page_label", "")
                        loc = f"{fname} 第{page}页" if page else fname
                        preview = src.get("text", "")[:300]
                        st.caption(f"**{loc}** · 相关度 {score:.0f}%\n\n{preview}...")

# 输入框
prompt = st.chat_input("请输入你的地理问题...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with chat_container:
        with st.chat_message("user"):
            st.markdown(prompt)

    retriever = get_retriever()
    retriever.reload()  # 确保使用最新索引数据
    llm = get_active_llm()

    if llm is None:
        with chat_container:
            with st.chat_message("assistant"):
                st.error("请先在系统设置中配置 DeepSeek API Key，或切换回本地模型。")
        st.session_state.messages.append({"role": "assistant", "content": "LLM 未配置，请检查系统设置。"})

    context, nodes = retriever.retrieve_as_context(prompt)

    if llm is not None and not context:
        # 知识库无结果时，兜底用 LLM 自身知识回答
        with chat_container:
            with st.chat_message("assistant"):
                placeholder = st.empty()
                placeholder.info("知识库中暂无相关内容，尝试基于模型自身知识回答...")
                full_response = ""
                try:
                    stream = llm.stream_generate(
                        f"请回答以下地理问题，如果不知道请诚实说明：\n{prompt}"
                    )
                    for chunk in stream:
                        full_response += chunk
                        placeholder.markdown(full_response + "▌")
                except Exception as e:
                    full_response = f"模型调用失败: {e}"
                    placeholder.markdown(full_response)
                prefix = "> ⚠️ 此回答未基于本地文档，仅供参考\n\n"
                placeholder.markdown(prefix + full_response)
        st.session_state.messages.append({
            "role": "assistant",
            "content": prefix + full_response,
            "sources": [],
        })
    elif llm is None:
        pass  # 已在上面提示，不重复处理
    else:
        with chat_container:
            with st.chat_message("assistant"):
                placeholder = st.empty()
                full_response = ""
                try:
                    stream = llm.rag_query(prompt, context, stream=True)
                    for chunk in stream:
                        full_response += chunk
                        placeholder.markdown(full_response + "▌")
                except Exception as e:
                    full_response = f"模型调用失败: {e}"
                    placeholder.markdown(full_response)
                placeholder.markdown(full_response)

                sources = []
                kp_tags_set = set()
                for node, score in zip(nodes, retriever.retrieve(prompt)[1]):
                    meta = node.metadata if hasattr(node, "metadata") else {}
                    sources.append({
                        "file_name": meta.get("file_name", "未知"),
                        "page_label": meta.get("page_label", ""),
                        "text": node.text[:300] if hasattr(node, "text") else str(node)[:300],
                        "score": score,
                    })
                    # 获取 chunk 对应的知识点标签
                    try:
                        from utils.knowledge_points import get_kps_for_chunk
                        kps = get_kps_for_chunk(node.node_id)
                        for kp in kps:
                            kp_tags_set.add(kp["kp_name"])
                    except Exception:
                        pass
                # 参考来源
                with st.expander("📚 参考来源"):
                    if kp_tags_set:
                        st.caption(f"🏷️ 涉及知识点：{'、'.join(list(kp_tags_set)[:8])}")
                    for i, src in enumerate(sources):
                        fname = src["file_name"]
                        page = src.get("page_label", "")
                        loc = f"详阅 {fname} 第{page}页" if page else f"详阅 {fname}"
                        st.caption(f"**{loc}** · 相关度 {src['score']*100:.0f}%\n\n{src['text']}...")

        st.session_state.messages.append({
            "role": "assistant",
            "content": full_response,
            "sources": sources,
        })

        log_question(prompt, full_response, str([s["file_name"] for s in sources]), profile_id=get_current_profile())
