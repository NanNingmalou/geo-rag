"""知识点管理 - 分类目录、数据回填、统计"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import json

from streamlit_app.shared import get_active_llm, init_session, is_teacher, render_profile_selector
from utils.knowledge_points import (
    load_taxonomy, sync_taxonomy_to_db, get_taxonomy_as_df,
    retrofit_all, build_kp_list_str, build_kp_mastery,
)
from utils.db import get_kp_taxonomy_stats, get_kp_assignment_stats, get_all_kps

init_session()
render_profile_selector()

if not is_teacher():
    st.warning("此功能仅教师可用，请切换到教师身份。")
    st.stop()

st.title("🧩 知识点管理")

tab1, tab2, tab3 = st.tabs(["📋 分类目录", "🔄 数据回填", "📊 状态统计"])

# ============================================================
# Tab 1: 分类目录
# ============================================================
with tab1:
    st.subheader("📋 知识点分类目录")

    # 同步按钮
    col_sync, col_stats = st.columns([1, 3])
    with col_sync:
        if st.button("🔄 同步到数据库", help="将 knowledge_taxonomy.json 同步到 SQLite"):
            count = sync_taxonomy_to_db()
            st.success(f"已同步 {count} 个知识点")
    with col_stats:
        stats = get_kp_taxonomy_stats()
        if stats["kp_count"] > 0:
            st.write(f"共 **{stats['domain_count']}** 个域 · **{stats['chapter_count']}** 个章 · **{stats['kp_count']}** 个知识点")

    # 目录树
    try:
        taxonomy = load_taxonomy()
    except Exception:
        st.warning("未找到 knowledge_taxonomy.json，请先创建分类目录文件")
        taxonomy = []

    if taxonomy:
        # 按域展示
        for domain in taxonomy:
            domain_name = domain.get("domain_name", "")
            domain_desc = domain.get("domain_desc", "")
            chapter_count = len(domain.get("chapters", []))
            kp_count = sum(
                len(ch.get("knowledge_points", [])) for ch in domain.get("chapters", [])
            )

            with st.expander(f"🌐 {domain_name} — {chapter_count}章 / {kp_count}个知识点"):
                st.caption(domain_desc)
                for chapter in domain.get("chapters", []):
                    ch_name = chapter.get("chapter_name", "")
                    kps = chapter.get("knowledge_points", [])

                    st.markdown(f"**📖 {ch_name}**（{len(kps)}个知识点）")
                    kp_names = [kp.get("kp_name", "") for kp in kps]
                    st.caption(" · ".join(kp_names))
                    st.divider()

    # 原始 JSON 查看
    with st.expander("🔧 原始 JSON 数据"):
        st.json(taxonomy[:2])  # 只显示前2个域避免太长
        st.caption("（仅展示前2个域，完整数据见 data/knowledge_taxonomy.json）")


# ============================================================
# Tab 2: 数据回填
# ============================================================
with tab2:
    st.subheader("🔄 数据回填")
    st.markdown("""
    使用 LLM 批量为现有数据打知识点标签：
    1. 将 **1038 个文本块** 分类到对应知识点
    2. 将 **自测历史记录** 分类到对应知识点

    此操作需要 LLM 可用（本地 Qwen 或 DeepSeek API）。
    """)

    # 显示当前状态
    kp_stats = get_kp_taxonomy_stats()
    chunk_stats = get_kp_assignment_stats()

    col1, col2, col3 = st.columns(3)
    col1.metric("分类目录知识点", kp_stats["kp_count"])
    col2.metric("已分类 Chunk", f"{chunk_stats['classified_chunks']}/{chunk_stats['total_chunks']}")
    col3.metric("待分类 Chunk", chunk_stats["unclassified"])

    llm = get_active_llm()

    if llm is None:
        st.warning("请先在 ⚙️ 系统设置 中配置 LLM")
    else:
        if st.button("🚀 开始回填", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            def update_progress(msg, current, total):
                status_text.text(f"{msg} ({current}/{total})")
                progress_bar.progress(min(current / max(total, 1), 1.0))

            with st.spinner("回填中，请耐心等待..."):
                try:
                    result = retrofit_all(llm, progress_callback=update_progress)
                    st.success(
                        f"回填完成！同步 {result['kps_synced']} 个知识点, "
                        f"分类 {result['chunks_classified']} 个文本块, "
                        f"分类 {result['quizzes_classified']} 条自测记录"
                    )
                except Exception as e:
                    st.error(f"回填失败: {e}")

        st.caption("提示：回填需要 LLM 逐批处理 1038 个 chunk + quiz_history，本地模型约需 5-15 分钟。")


# ============================================================
# Tab 3: 状态统计
# ============================================================
with tab3:
    st.subheader("📊 分类状态统计")

    # Taxonomy stats
    st.markdown("### 分类目录")
    tax_stats = get_kp_taxonomy_stats()
    if tax_stats["kp_count"] > 0:
        col1, col2, col3 = st.columns(3)
        col1.metric("知识点总数", tax_stats["kp_count"])
        col2.metric("章数", tax_stats["chapter_count"])
        col3.metric("域数", tax_stats["domain_count"])
    else:
        st.info("数据库中没有知识点数据，请先在「分类目录」标签页中点击「同步到数据库」")

    # Chunk classification stats
    st.markdown("### 文本块分类")
    chunk_stats = get_kp_assignment_stats()
    if chunk_stats["total_chunks"] > 0:
        col1, col2, col3 = st.columns(3)
        col1.metric("总 Chunk 数", chunk_stats["total_chunks"])
        col2.metric("已分类", chunk_stats["classified_chunks"],
                   delta=f"{chunk_stats['classified_chunks']/chunk_stats['total_chunks']*100:.0f}%")
        col3.metric("待分类", chunk_stats["unclassified"],
                   delta=f"-{chunk_stats['unclassified']}" if chunk_stats["unclassified"] > 0 else "完成")
    else:
        st.info("尚未建立索引，请先在知识库管理页构建索引")

    # Quiz classification stats
    st.markdown("### 自测记录分类")
    try:
        from utils.db import get_db
        conn = get_db()
        total_quiz = conn.execute("SELECT COUNT(*) FROM quiz_history").fetchone()[0]
        classified_quiz = conn.execute("SELECT COUNT(DISTINCT quiz_id) FROM quiz_knowledge_points").fetchone()[0]
        conn.close()

        col1, col2, col3 = st.columns(3)
        col1.metric("总自测记录", total_quiz)
        col2.metric("已分类", classified_quiz,
                   delta=f"{classified_quiz/total_quiz*100:.0f}%" if total_quiz > 0 else "0%")
        col3.metric("待分类", total_quiz - classified_quiz)
    except Exception:
        st.info("暂无自测记录")

    # Chunk 质量分布
    st.markdown("### 📊 Chunk 质量分分布")
    try:
        from utils.db import get_chunk_quality_stats
        qstats = get_chunk_quality_stats()
        if qstats["total_feedback"] > 0:
            col_q1, col_q2, col_q3, col_q4 = st.columns(4)
            col_q1.metric("反馈总数", qstats["total_feedback"])
            col_q2.metric("有反馈的 Chunk", qstats["chunks_with_feedback"])
            col_q3.metric("高质量 (>0.6)", qstats["high_quality"])
            col_q4.metric("低质量 (<0.4)", qstats["low_quality"])
            st.caption("质量分由 feedback 实时计算（最少3条才生效），在检索重排序中自动应用")
        else:
            st.caption("暂无反馈数据。完成自测后，检索到的 chunk 会自动记录反馈。")
    except Exception:
        st.caption("暂无质量分数据")

    # KP mastery preview
    st.markdown("### 知识点掌握度预览")
    try:
        kp_df = build_kp_mastery()
        if not kp_df.empty and kp_df["total"].sum() > 0:
            kp_with_data = kp_df[kp_df["total"] > 0].sort_values("mastery_rate")
            st.dataframe(
                kp_with_data[["kp_name", "chapter_name", "domain_name", "mastery_rate", "total", "correct"]],
                column_config={
                    "kp_name": "知识点",
                    "chapter_name": "章",
                    "domain_name": "域",
                    "mastery_rate": st.column_config.NumberColumn("掌握率", format="%.1f%%"),
                    "total": "答题次数",
                    "correct": "正确次数",
                },
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("暂无自测数据，完成自测并回填后这里将显示各知识点的掌握度")
    except Exception:
        st.info("暂无数据")
