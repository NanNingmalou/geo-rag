"""高频问答统计 + 知识自测"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import time
import random

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from streamlit_app.shared import get_active_llm, get_retriever, init_session, get_profile_filter, render_profile_selector
from utils.db import get_top_questions, get_quiz_stats, get_question_error_stats, clear_question_log

init_session()
render_profile_selector()
from utils.quiz import get_quiz_questions, judge_answer, save_result, build_domain_mastery, GEOGRAPHY_DOMAINS, analyze_knowledge_dependency, predict_risk
from utils.knowledge_points import (
    build_domain_mastery_v2, build_kp_mastery, get_chapter_heatmap_data,
    get_weakest_kps, get_chapter_mastery_sorted, sync_taxonomy_to_db,
)

st.title("📊 高频问答 & 自测")

tab1, tab2, tab3 = st.tabs(["🔥 高频问题", "✍️ 知识自测", "📈 学情分析"])

# === 高频问题 ===
with tab1:
    st.subheader("🔥 高频问题 Top 20")
    questions = get_top_questions(20, profile_id=get_profile_filter())

    if not questions:
        st.info("暂无问答记录，去问答页提问后再来")
    else:
        for i, q in enumerate(questions):
            col1, col2 = st.columns([6, 1])
            with col1:
                st.write(f"**#{i+1}** {q['question']} — {q['cnt']} 次")
            with col2:
                st.caption(q.get("last_asked", "")[:10])

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            st.download_button(
                "📋 导出 CSV",
                "\n".join(f"{q['question']},{q['cnt']}" for q in questions),
                "top_questions.csv",
                "text/csv",
                use_container_width=True,
            )
        with col_btn2:
            if st.button("🗑️ 清空记录", type="secondary", use_container_width=True):
                clear_question_log()
                st.success("已清空")
                st.rerun()

# === 知识自测 ===
with tab2:
    st.subheader("✍️ 知识自测")

    col1, col2 = st.columns(2)
    with col1:
        mode = st.radio("出题模式", ["top", "bank", "wrong"],
                        format_func=lambda x: {"top": "按热度出题", "bank": "题库出题", "wrong": "错题重测"}[x],
                        horizontal=False)
    with col2:
        count = st.slider("题目数量", 3, 20, 5)

    # 题库模式筛选器
    bank_difficulty = None
    bank_kp_id = None
    if mode == "bank":
        col_d, col_k = st.columns(2)
        with col_d:
            bank_difficulty = st.selectbox("难度筛选", ["全部", "简单", "中等", "困难"],
                                           format_func=lambda x: x if x != "全部" else "全部难度")
            if bank_difficulty == "全部":
                bank_difficulty = None
            else:
                bank_difficulty = {"简单": "easy", "中等": "medium", "困难": "hard"}[bank_difficulty]
        with col_k:
            from utils.db import get_all_kps
            all_kps = get_all_kps()
            kp_options = [("全部知识点", None)] + [(f"{kp['kp_name']} [{kp['domain_name']}]", kp['kp_id']) for kp in all_kps]
            selected_kp = st.selectbox("知识点筛选", [opt[0] for opt in kp_options])
            for label, kid in kp_options:
                if label == selected_kp:
                    bank_kp_id = kid
                    break

    # 初始化自测状态
    if "quiz_state" not in st.session_state:
        st.session_state.quiz_state = None  # None=未开始, "running", "done"
        st.session_state.quiz_idx = 0
        st.session_state.quiz_questions = []
        st.session_state.quiz_results = []
        st.session_state.quiz_start_time = 0
        st.session_state.quiz_session_id = ""
        st.session_state.quiz_mode = "top"

    if st.session_state.quiz_state is None:
        if st.button("🚀 开始自测"):
            import uuid
            st.session_state.quiz_state = "running"
            st.session_state.quiz_idx = 0
            st.session_state.quiz_results = []
            st.session_state.quiz_start_time = time.time()
            st.session_state.quiz_session_id = str(uuid.uuid4())
            st.session_state.quiz_questions = get_quiz_questions(mode, count, bank_difficulty, bank_kp_id)
            st.session_state.quiz_mode = mode  # 记住模式，答题时判断是否用 RAG
            st.rerun()

    elif st.session_state.quiz_state == "running":
        idx = st.session_state.quiz_idx
        questions = st.session_state.quiz_questions

        if idx >= len(questions):
            st.session_state.quiz_state = "done"
            st.rerun()
        else:
            q = questions[idx]
            st.markdown(f"### 第 {idx+1}/{len(questions)} 题")
            st.markdown(f"**{q}**")

            user_answer = st.text_area("你的回答:", key=f"quiz_answer_{idx}", height=100)

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅ 提交答案", key=f"submit_{idx}") and user_answer.strip():
                    t0 = time.time()
                    llm = get_active_llm()
                    retriever = get_retriever()

                    # 获取标准答案：题库模式直接用预设，其他用 RAG
                    quiz_mode = st.session_state.get("quiz_mode", "top")
                    retrieved_nodes = []
                    if quiz_mode == "bank":
                        from utils.db import get_bank_standard_answer
                        standard = get_bank_standard_answer(q) or ""
                    else:
                        context, nodes = retriever.retrieve_as_context(q)
                        retrieved_nodes = nodes
                        standard = llm.rag_query(q, context, stream=False) if context else llm.generate(q)

                    # 评判
                    from utils.quiz import judge_standard_answer
                    judge = judge_standard_answer(q, standard, user_answer, llm=llm)
                    time_spent = time.time() - t0

                    st.session_state.quiz_results.append({
                        "question": q,
                        "user_answer": user_answer,
                        "standard_answer": standard,
                        "result": judge["result"],
                        "explanation": judge["explanation"],
                        "time_spent": time_spent,
                    })
                    st.session_state.quiz_idx = idx + 1

                    # 保存到数据库（自动分类到知识点 + session追踪）
                    save_result(q, user_answer, {
                        "standard_answer": standard,
                        "result": judge["result"],
                        "explanation": judge["explanation"],
                    }, time_spent, llm=llm,
                        session_id=st.session_state.get("quiz_session_id", ""),
                        profile_id=get_profile_filter() or "",
                        retrieved_chunk_ids=[n.node_id for n in retrieved_nodes])

                    st.rerun()

            with col_b:
                if st.button("⏭️ 跳过", key=f"skip_{idx}"):
                    st.session_state.quiz_idx = idx + 1
                    st.rerun()

            # 统计
            total = len(st.session_state.quiz_results)
            correct = sum(1 for r in st.session_state.quiz_results if r["result"] == "正确")
            elapsed = time.time() - st.session_state.quiz_start_time
            st.caption(f"已答: {total} | ✅正确: {correct} | 📈正确率: {correct/total*100:.0f}% | ⏱️用时: {elapsed:.0f}秒")

    else:
        # 完成
        results = st.session_state.quiz_results
        total = len(results)
        correct = sum(1 for r in results if r["result"] == "正确")
        partial = sum(1 for r in results if r["result"] == "部分正确")
        wrong = total - correct - partial

        st.success(f"🎉 自测完成！正确率: {correct/total*100:.0f}%")
        col1, col2, col3 = st.columns(3)
        col1.metric("✅ 正确", correct)
        col2.metric("⚠️ 部分正确", partial)
        col3.metric("❌ 错误", wrong)

        st.divider()
        for i, r in enumerate(results):
            emoji = {"正确": "✅", "部分正确": "⚠️", "错误": "❌"}.get(r["result"], "❓")
            with st.expander(f"{emoji} {r['question'][:50]}"):
                st.write(f"**你的回答**: {r['user_answer']}")
                st.write(f"**标准答案**: {r['standard_answer']}")
                st.write(f"**评判**: {r['explanation']}")

        if st.button("🔄 再来一轮"):
            st.session_state.quiz_state = None
            st.rerun()

# === 学情分析 ===
with tab3:
    st.subheader("📈 学情分析")

    if st.button("🔍 开始分析", type="primary"):
        # 数据校验
        stats = get_quiz_stats(profile_id=get_profile_filter())
        if not stats or stats["total"] == 0:
            st.warning("暂无自测记录，请先完成自测后再来分析")
        else:
            llm = get_active_llm()
            if llm is None:
                st.error("请先在系统设置中配置 LLM")
            else:
                with st.status("分析中...", expanded=True) as status:
                    # --- 1. 问题错误率柱状图 ---
                    status.update(label="计算问题错误率...")
                    error_rows = get_question_error_stats(15, profile_id=get_profile_filter())
                    if error_rows:
                        df_errors = pd.DataFrame(error_rows)
                        df_errors["错误率"] = (
                            (df_errors["wrong"] + df_errors["partial"] * 0.5)
                            / df_errors["total"]
                            * 100
                        ).round(1)
                        df_errors["题目标签"] = df_errors["question"].str[:30] + "..."
                        df_errors = df_errors.sort_values("错误率", ascending=True)

                        fig_bar = px.bar(
                            df_errors,
                            x="错误率",
                            y="题目标签",
                            orientation="h",
                            color="错误率",
                            color_continuous_scale="Reds",
                            title="问题错误率排行",
                            text=df_errors["错误率"].apply(lambda v: f"{v:.0f}%"),
                        )
                        fig_bar.update_layout(height=400, yaxis={"categoryorder": "total ascending"})
                        st.plotly_chart(fig_bar, use_container_width=True)
                    else:
                        st.info("暂无自测记录")

                    # --- 2. 知识域雷达图 ---
                    status.update(label="LLM 分类知识域...")
                    domain_mastery = build_domain_mastery(llm)
                    if domain_mastery:
                        domains = []
                        rates = []
                        # 保持 GEOGRAPHY_DOMAINS 的顺序
                        for name, _desc in GEOGRAPHY_DOMAINS:
                            if name in domain_mastery:
                                domains.append(name)
                                rates.append(domain_mastery[name]["rate"])

                        if rates:
                            fig_radar = go.Figure()
                            fig_radar.add_trace(go.Scatterpolar(
                                r=rates + [rates[0]],
                                theta=domains + [domains[0]],
                                fill="toself",
                                fillcolor="rgba(59, 130, 246, 0.2)",
                                line=dict(color="#3b82f6", width=2),
                                name="掌握度 (%)",
                            ))
                            fig_radar.update_layout(
                                polar=dict(radialaxis=dict(range=[0, 100], ticksuffix="%")),
                                title="知识域掌握度雷达图",
                                height=450,
                            )
                            st.plotly_chart(fig_radar, use_container_width=True)

                            # --- 2.5 章×域掌握度热力图 ---
                            status.update(label="生成知识点热力图...")
                            heatmap_data = get_chapter_heatmap_data(profile_id=get_profile_filter())
                            if not heatmap_data.empty:
                                fig_heat = px.imshow(
                                    heatmap_data,
                                    color_continuous_scale="RdYlGn",
                                    range_color=[0, 100],
                                    title="知识域 × 章 掌握度热力图",
                                    text_auto=".0f",
                                    aspect="auto",
                                )
                                fig_heat.update_layout(height=500)
                                st.plotly_chart(fig_heat, use_container_width=True)

                            # --- 2.6 知识点掌握度排行 ---
                            kp_mastery = build_kp_mastery(profile_id=get_profile_filter())
                            if not kp_mastery.empty:
                                kp_display = kp_mastery[kp_mastery["total"] > 0].copy()
                                if not kp_display.empty:
                                    kp_display = kp_display.sort_values("mastery_rate")
                                    kp_display["标签"] = kp_display["kp_name"] + " [" + kp_display["domain_name"] + "]"
                                    fig_kp = px.bar(
                                        kp_display,
                                        x="mastery_rate",
                                        y="标签",
                                        orientation="h",
                                        color="domain_name",
                                        title="知识点掌握度排行",
                                        labels={"mastery_rate": "掌握率 (%)", "标签": "知识点", "domain_name": "知识域"},
                                        text=kp_display["mastery_rate"].apply(lambda v: f"{v:.0f}%"),
                                    )
                                    fig_kp.update_layout(height=max(350, len(kp_display) * 25))
                                    st.plotly_chart(fig_kp, use_container_width=True)

                            # --- 2.7 最薄弱知识点 Top-N ---
                            weakest_kps = get_weakest_kps(threshold=100, limit=8, profile_id=get_profile_filter())
                            if weakest_kps:
                                df_weak = pd.DataFrame(weakest_kps)
                                df_weak.index = range(1, len(df_weak) + 1)
                                df_weak["掌握率"] = df_weak["mastery_rate"].apply(lambda v: f"{v:.0f}%")
                                st.markdown("### 🔴 最薄弱知识点")
                                st.dataframe(
                                    df_weak[["kp_name", "chapter_name", "domain_name", "掌握率", "total"]],
                                    column_config={
                                        "kp_name": "知识点",
                                        "chapter_name": "所属章",
                                        "domain_name": "所属域",
                                        "掌握率": "掌握率",
                                        "total": "答题次数",
                                    },
                                    use_container_width=True,
                                )

                            # --- 2.8 掌握度趋势折线图 ---
                            status.update(label="生成学习趋势...")
                            from utils.knowledge_points import build_domain_timelines, build_progress_delta

                            domain_timelines = build_domain_timelines(profile_id=get_profile_filter())
                            if domain_timelines:
                                fig_trend = go.Figure()
                                colors = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"]
                                for i, (domain_name, df) in enumerate(domain_timelines.items()):
                                    color = colors[i % len(colors)]
                                    fig_trend.add_trace(go.Scatter(
                                        x=df["session_label"],
                                        y=df["cumulative_rate"],
                                        mode="lines+markers",
                                        name=domain_name,
                                        line=dict(color=color, width=2),
                                        marker=dict(size=6),
                                    ))
                                fig_trend.update_layout(
                                    title="知识域掌握度趋势",
                                    xaxis_title="自测轮次",
                                    yaxis_title="累计掌握率 (%)",
                                    yaxis=dict(range=[0, 105], ticksuffix="%"),
                                    height=400,
                                    hovermode="x unified",
                                )
                                st.plotly_chart(fig_trend, use_container_width=True)

                            # --- 2.9 进步速度排行 ---
                            delta_df = build_progress_delta()
                            if not delta_df.empty:
                                st.markdown("### 🚀 进步速度排行")
                                col_d1, col_d2 = st.columns(2)
                                with col_d1:
                                    st.markdown("**进步最快**")
                                    improving = delta_df[delta_df["delta"] > 0].head(5)
                                    if not improving.empty:
                                        for _, row in improving.iterrows():
                                            st.write(f"📈 **{row['kp_name']}** +{row['delta']:.0f}%")
                                    else:
                                        st.caption("暂无显著进步")
                                with col_d2:
                                    st.markdown("**需要关注**")
                                    declining = delta_df[delta_df["delta"] < 0].tail(5)
                                    if not declining.empty:
                                        for _, row in declining.iterrows():
                                            st.write(f"📉 **{row['kp_name']}** {row['delta']:.0f}%")
                                    else:
                                        st.caption("暂无退步趋势")

                            # --- 3. 薄弱点分析 ---
                            status.update(label="LLM 生成薄弱点分析...")
                            weakest = min(domain_mastery.items(), key=lambda kv: kv[1]["rate"])
                            strongest = max(domain_mastery.items(), key=lambda kv: kv[1]["rate"])

                            domain_summary = "\n".join(
                                f"- {d}: 掌握率 {v['rate']}%（{v['correct']}/{v['total']}）"
                                for d, v in domain_mastery.items()
                            )

                            analysis_prompt = f"""你是一个高中地理教学分析专家。请根据以下自测数据分析学生的知识薄弱点。

知识域掌握率：
{domain_summary}

最薄弱领域：{weakest[0]}（{weakest[1]['rate']}%）
最擅长领域：{strongest[0]}（{strongest[1]['rate']}%）

请用100-150字给出：
1. 薄弱点在哪
2. 可能的原因
3. 一条具体的复习建议"""
                            try:
                                analysis = llm.generate(analysis_prompt, max_tokens=256, temperature=0.3)
                            except Exception:
                                analysis = "LLM 分析失败，请重试"

                            st.markdown("### 🧠 薄弱点分析")
                            st.info(analysis)

                            # --- 4. 知识依赖分析 ---
                            status.update(label="推理知识依赖关系...")
                            st.markdown("### 🔗 知识依赖分析")
                            dependency = analyze_knowledge_dependency(llm, domain_mastery)
                            st.info(dependency)

                            # --- 5. 薄弱点风险预测 ---
                            status.update(label="预测薄弱点风险...")
                            st.markdown("### 🔮 风险预测")
                            risk = predict_risk(llm, domain_mastery)
                            st.info(risk)

                            # --- 6. KP 级知识点分析 ---
                            kp_df = build_kp_mastery(profile_id=get_profile_filter())
                            if not kp_df.empty and kp_df["total"].sum() > 0:
                                status.update(label="生成知识点级分析...")
                                kp_with_data = kp_df[kp_df["total"] > 0]
                                if len(kp_with_data) >= 3:
                                    kp_summary = "\n".join(
                                        f"- {row['kp_name']}（{row['domain_name']}·{row['chapter_name']}）: "
                                        f"掌握率 {row['mastery_rate']}%（{int(row['total'])}次）"
                                        for _, row in kp_with_data.iterrows()
                                    )

                                    kp_analysis_prompt = f"""你是一个高中地理教学分析专家。以下是学生各知识点的掌握情况：

{kp_summary}

请用150字以内：
1. 找出3个最需要加强的的知识点及其薄弱原因
2. 给出针对性复习建议（按优先级排序）"""
                                    try:
                                        kp_analysis = llm.generate(kp_analysis_prompt, max_tokens=256, temperature=0.3)
                                    except Exception:
                                        kp_analysis = "LLM 分析失败，请重试"

                                    st.markdown("### 🎯 知识点级分析")
                                    st.info(kp_analysis)
                        else:
                            st.info("暂无足够数据绘制知识域分析")

                    status.update(label="分析完成!", state="complete")

                    # 导出报告按钮
                    st.divider()
                    st.subheader("📥 导出报告")
                    if st.button("📥 生成学习报告 (.docx)", key="export_report_analysis"):
                        from utils.report_generator import generate_report
                        report_path = generate_report()
                        with open(report_path, "rb") as rf:
                            st.download_button(
                                "📥 点击下载报告",
                                rf,
                                file_name=os.path.basename(report_path),
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                use_container_width=True,
                            )
    else:
        st.info("点击「开始分析」生成学情报告")
