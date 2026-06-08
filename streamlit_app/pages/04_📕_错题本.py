"""错题本 - 错题汇总、重测、导出"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import time
from datetime import datetime

from streamlit_app.shared import get_active_llm, get_retriever, init_session, get_profile_filter, render_profile_selector
from utils.db import get_wrong_questions, get_quiz_detail, mark_mastered
from utils.quiz import judge_standard_answer, save_result

init_session()
render_profile_selector()

st.title("📕 错题本")

wrong_questions = get_wrong_questions(profile_id=get_profile_filter())

if not wrong_questions:
    st.success("暂无错题，继续保持！")
else:
    mastered_count = sum(1 for q in wrong_questions if q["wrong_count"] >= 2)

    col1, col2, col3 = st.columns(3)
    col1.metric("待复习", len(wrong_questions))

    st.divider()

    for q_data in wrong_questions:
        q = q_data["question"]
        detail = get_quiz_detail(q)

        # 判断是否连续答对
        recent_results = [d["result"] for d in detail[:3]]
        should_master = len(recent_results) >= 2 and all(r == "正确" for r in recent_results[:2])

        emoji = {"正确": "✅", "部分正确": "⚠️", "错误": "❌"}
        last_result = detail[0]["result"] if detail else "错误"
        status_emoji = emoji.get(last_result, "❓")

        with st.expander(f"{status_emoji} {q[:80]} · 错{q_data['wrong_count']}次", expanded=(last_result != "正确")):
            for d in detail[:3]:
                st.write(f"**你的回答** ({d['created_at'][:10]}): {d['user_answer'][:200]}")
                st.write(f"**标准答案**: {d.get('standard_answer', '')[:200]}")
                st.write(f"**评判**: {d.get('explanation', '')[:200]}")
                st.caption("---")

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button(f"🔁 重测此题", key=f"retry_{hash(q)}"):
                    st.session_state.retry_question = q
                    st.rerun()
            with col_b:
                if should_master and st.button(f"✅ 标记已掌握", key=f"master_{hash(q)}"):
                    mark_mastered(q)
                    st.success(f"已掌握！")
                    st.rerun()

# --- 重测模式 ---
if "retry_question" in st.session_state and st.session_state.retry_question:
    q = st.session_state.retry_question
    st.divider()
    st.subheader(f"🔁 重测: {q}")

    user_answer = st.text_area("你的回答:", key="retry_answer", height=100)

    if st.button("✅ 提交") and user_answer.strip():
        llm = get_active_llm()
        retriever = get_retriever()

        context, _ = retriever.retrieve_as_context(q)
        standard = llm.rag_query(q, context, stream=False) if context else llm.generate(q)
        judge = judge_standard_answer(q, standard, user_answer, llm=llm)
        import uuid
        save_result(q, user_answer, {"standard_answer": standard, "result": judge["result"], "explanation": judge["explanation"]}, llm=llm, session_id=str(uuid.uuid4()), profile_id=get_profile_filter() or "")

        st.info(f"**结果**: {judge['result']}")
        st.write(f"**标准答案**: {standard}")
        st.write(f"**说明**: {judge['explanation']}")

        if st.button("返回错题本"):
            del st.session_state.retry_question
            st.rerun()
