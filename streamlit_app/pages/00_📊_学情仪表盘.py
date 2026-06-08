"""学情仪表盘 - 打开即看的学情总览，无需点击任何按钮"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from streamlit_app.shared import init_session, get_active_llm, get_retriever, get_profile_filter, is_teacher, render_profile_selector

init_session()
render_profile_selector()

st.title("📊 学情仪表盘")

# ---- 数据加载（全部复用已有函数） ----

from utils.db import get_db

def _get_overview_stats(profile_id=None):
    """获取概览统计数据"""
    conn = get_db()
    where, params = ("", [])
    if profile_id is not None:
        where, params = ("WHERE profile_id = ?", [profile_id])

    total = conn.execute(f"SELECT COUNT(*) FROM quiz_history {where}", params).fetchone()[0]
    if total == 0:
        conn.close()
        return {"total": 0, "correct": 0, "partial": 0, "wrong": 0, "rate": 0, "kp_count": 0, "session_count": 0, "bank_count": 0}

    correct = conn.execute(f"SELECT COUNT(*) FROM quiz_history WHERE result='正确' {'AND profile_id = ?' if profile_id else ''}", params).fetchone()[0]
    partial = conn.execute(f"SELECT COUNT(*) FROM quiz_history WHERE result='部分正确' {'AND profile_id = ?' if profile_id else ''}", params).fetchone()[0]
    wrong = conn.execute(f"SELECT COUNT(*) FROM quiz_history WHERE result='错误' {'AND profile_id = ?' if profile_id else ''}", params).fetchone()[0]
    rate = (correct + partial * 0.5) / total * 100 if total > 0 else 0

    kp_count = conn.execute("SELECT COUNT(DISTINCT kp_id) FROM quiz_knowledge_points").fetchone()[0]
    session_count = conn.execute(
        f"SELECT COUNT(DISTINCT session_id) FROM quiz_history WHERE session_id IS NOT NULL {'AND profile_id = ?' if profile_id else ''}", params
    ).fetchone()[0]
    bank_count = conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]
    conn.close()

    return {
        "total": total, "correct": correct, "partial": partial, "wrong": wrong,
        "rate": round(rate, 1), "kp_count": kp_count, "session_count": session_count,
        "bank_count": bank_count,
    }


# ---- 概览卡片 ----

st.subheader("📋 学习概览")

stats = _get_overview_stats(profile_id=get_profile_filter())

if stats["total"] == 0:
    st.info("👋 还没有学习数据。去 **高频问答与自测** 页面开始你的第一轮自测吧！")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.page_link("pages/03_📊_高频问答与自测.py", label="✍️ 开始自测", icon="✍️")
    with col_b:
        st.page_link("pages/02_💬_智能问答.py", label="💬 智能问答", icon="💬")
    with col_c:
        st.page_link("pages/01_📚_知识库管理.py", label="📚 知识库管理", icon="📚")
else:
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("累计答题", f"{stats['total']} 题")
    with col2:
        st.metric("整体正确率", f"{stats['rate']:.0f}%",
                 delta=f"✅{stats['correct']} ⚠️{stats['partial']} ❌{stats['wrong']}")
    with col3:
        st.metric("已覆盖知识点", f"{stats['kp_count']} 个" if stats['kp_count'] > 0 else "待分类")
    with col4:
        st.metric("自测轮次", f"{stats['session_count']} 轮")
    with col5:
        st.metric("题库题目", f"{stats['bank_count']} 题")

    st.divider()

    # ---- 知识域掌握卡片 ----

    st.subheader("📈 知识域掌握度")

    # 尝试从 KP 数据汇总（v2），fallback 到 LLM 分类
    from utils.knowledge_points import build_domain_mastery_v2, get_weakest_kps, build_kp_mastery
    from utils.quiz import GEOGRAPHY_DOMAINS, build_domain_mastery

    kp_df_dashboard = build_kp_mastery(profile_id=get_profile_filter())
    domain_mastery = build_domain_mastery_v2(kp_df_dashboard)

    if not domain_mastery:
        # fallback: 尝试 LLM 分类（但可能没有 LLM）
        try:
            llm = get_active_llm()
            if llm:
                domain_mastery = build_domain_mastery(llm)
        except Exception:
            domain_mastery = {}

    if domain_mastery:
        rows = []
        domain_data = []
        for i in range(0, len(GEOGRAPHY_DOMAINS), 3):
            rows.append(GEOGRAPHY_DOMAINS[i:i+3])

        for row_chunk in rows:
            cols = st.columns(3)
            for j, (name, desc) in enumerate(row_chunk):
                data = domain_mastery.get(name, {})
                rate = data.get("rate", 0)
                total = data.get("total", 0)
                with cols[j]:
                    # 颜色判断
                    if rate >= 70:
                        color = "green"
                    elif rate >= 40:
                        color = "orange"
                    else:
                        color = "red"

                    st.markdown(f"**{name}**")
                    st.progress(min(rate / 100, 1.0))
                    st.caption(f":{color}[{rate:.0f}%] · {total} 题")
    else:
        st.caption("暂无知识域数据。完成自测并运行知识点回填后，这里将显示各域的掌握度。")

    st.divider()

    # ---- 趋势 + 薄弱点 ----

    st.subheader("📉 学习动态")

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**掌握度趋势**")
        from utils.knowledge_points import build_mastery_timeline
        timeline_df = build_mastery_timeline(profile_id=get_profile_filter())

        if not timeline_df.empty and len(timeline_df) >= 2:
            fig_trend = go.Figure()
            fig_trend.add_trace(go.Scatter(
                x=timeline_df["session_label"],
                y=timeline_df["cumulative_rate"],
                mode="lines+markers",
                line=dict(color="#3b82f6", width=2),
                marker=dict(size=8, color="#3b82f6"),
                fill="tozeroy",
                fillcolor="rgba(59, 130, 246, 0.1)",
            ))
            fig_trend.update_layout(
                xaxis_title="自测轮次",
                yaxis=dict(title="累计掌握率", range=[0, 105], ticksuffix="%"),
                height=280,
                margin=dict(l=10, r=10, t=10, b=10),
                showlegend=False,
            )
            st.plotly_chart(fig_trend, use_container_width=True)
        elif not timeline_df.empty and len(timeline_df) == 1:
            rate = timeline_df.iloc[0]["cumulative_rate"]
            st.info(f"第1轮掌握率：{rate:.0f}%。完成更多轮自测后将显示趋势曲线。")
        else:
            st.info("暂无趋势数据。请先运行知识点回填（知识点管理页 → 开始回填）。")

    with col_right:
        st.markdown("**最薄弱知识点**")
        weakest = get_weakest_kps(threshold=100, limit=5, profile_id=get_profile_filter())
        if weakest:
            for i, kp in enumerate(weakest):
                rate = kp["mastery_rate"]
                color = "red" if rate < 40 else ("orange" if rate < 60 else "green")
                st.write(f"{i+1}. :{color}[{kp['kp_name']}] — {rate:.0f}%")
                st.caption(f"   {kp['domain_name']} · {kp['chapter_name']} · {kp.get('total', 0)}题")
        else:
            st.info("暂无知识点数据。请先运行知识点回填。")

    st.divider()

    # ---- 学习计划进度 ----

    from utils.db import get_active_plan
    active_plan, plan_items = get_active_plan()

    st.subheader("📋 学习计划")
    if active_plan and plan_items:
        total_pi = len(plan_items)
        completed_pi = sum(1 for i in plan_items if i["status"] == "completed")
        next_item = next((i for i in plan_items if i["status"] == "pending"), None)

        col_p1, col_p2 = st.columns([1, 2])
        with col_p1:
            st.metric("计划进度", f"{completed_pi}/{total_pi}")
            st.progress(completed_pi / total_pi if total_pi > 0 else 0)
        with col_p2:
            if next_item:
                st.caption(f"下一步：{next_item['description']}")
            else:
                st.caption("全部完成！")
            st.page_link("pages/08_📋_学习计划.py", label="📋 查看完整计划", icon="📋")
    else:
        st.info("还没有学习计划")
        st.page_link("pages/08_📋_学习计划.py", label="📋 生成学习计划", icon="📋")

    st.divider()

    # ---- 导出报告 ----

    if stats["total"] > 0:
        st.subheader("📥 导出报告")
        if st.button("📥 生成学习报告 (.docx)", use_container_width=True):
            from utils.report_generator import generate_report
            report_path = generate_report()
            with open(report_path, "rb") as f:
                st.download_button(
                    "📥 点击下载报告",
                    f,
                    file_name=os.path.basename(report_path),
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )
        st.divider()

    # ---- 快捷操作 ----

    st.subheader("🚀 快捷操作")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.page_link("pages/03_📊_高频问答与自测.py", label="✍️ 开始自测", icon="✍️",
                     use_container_width=True)
    with col_b:
        st.page_link("pages/04_📕_错题本.py", label="📕 查看错题", icon="📕",
                     use_container_width=True)
    with col_c:
        st.page_link("pages/05_🧩_知识点管理.py", label="🧩 知识点管理", icon="🧩",
                     use_container_width=True)

# ---- 底部状态 ----

st.divider()
st.caption(f"数据更新时间：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')} · 数据来源：本地 SQLite")
