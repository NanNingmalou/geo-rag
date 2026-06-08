"""题库管理 - 教师自定义题目：增删改查、筛选、CSV导入"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import io

from streamlit_app.shared import init_session, is_teacher, render_profile_selector
from utils.db import (
    get_bank_questions, get_bank_question_count,
    add_bank_question, update_bank_question, delete_bank_question,
    get_all_kps,
)

init_session()
render_profile_selector()

if not is_teacher():
    st.warning("此功能仅教师可用，请切换到教师身份。")
    st.stop()

st.title("📝 题库管理")

# ---- 搜索与筛选栏 ----

col_search, col_diff, col_kp = st.columns([2, 1, 2])

with col_search:
    search_text = st.text_input("🔍 搜索题目", placeholder="输入关键词...", key="bank_search")

with col_diff:
    diff_filter = st.selectbox("难度", ["全部", "简单", "中等", "困难"],
                               key="bank_diff")
    if diff_filter == "全部":
        diff_filter = None
    else:
        diff_filter = {"简单": "easy", "中等": "medium", "困难": "hard"}[diff_filter]

with col_kp:
    all_kps = get_all_kps()
    kp_labels = ["全部知识点"] + [f"{kp['kp_name']} [{kp['domain_name']}]" for kp in all_kps]
    kp_raw = [None] + [kp["kp_id"] for kp in all_kps]
    kp_index = st.selectbox("知识点", range(len(kp_labels)), format_func=lambda i: kp_labels[i], key="bank_kp")
    kp_filter = kp_raw[kp_index]

# ---- 操作按钮 ----

col_add, col_import, col_stats = st.columns([1, 1, 3])

with col_add:
    if st.button("➕ 添加题目", use_container_width=True):
        st.session_state.show_add_form = True

with col_import:
    if st.button("📥 导入CSV", use_container_width=True):
        st.session_state.show_import = True

with col_stats:
    total = get_bank_question_count()
    st.caption(f"题库共 **{total}** 题")

# ---- 添加题目表单 ----

if st.session_state.get("show_add_form"):
    with st.form("add_question_form"):
        st.subheader("添加新题目")
        new_question = st.text_area("题目", height=80, placeholder="输入题目内容...")
        new_answer = st.text_area("标准答案", height=100, placeholder="输入标准答案...")
        col1, col2, col3 = st.columns(3)
        with col1:
            new_diff = st.selectbox("难度", ["easy", "medium", "hard"],
                                    format_func=lambda x: {"easy": "简单", "medium": "中等", "hard": "困难"}[x])
        with col2:
            kp_choices = ["无"] + [kp["kp_name"] for kp in all_kps]
            kp_ids = [""] + [kp["kp_id"] for kp in all_kps]
            new_kp_idx = st.selectbox("知识点", range(len(kp_choices)),
                                      format_func=lambda i: kp_choices[i])
            new_kp_id = kp_ids[new_kp_idx]
        with col3:
            new_tags = st.text_input("标签（逗号分隔）", placeholder="如: 自然地理,气候")

        col_submit, col_cancel = st.columns(2)
        with col_submit:
            submitted = st.form_submit_button("✅ 保存", use_container_width=True, type="primary")
        with col_cancel:
            cancelled = st.form_submit_button("❌ 取消", use_container_width=True)

        if submitted and new_question.strip() and new_answer.strip():
            add_bank_question(new_question.strip(), new_answer.strip(), new_diff, new_kp_id, new_tags)
            st.success("题目已添加！")
            st.session_state.show_add_form = False
            st.rerun()
        elif submitted:
            st.error("题目和标准答案不能为空")
        if cancelled:
            st.session_state.show_add_form = False
            st.rerun()

# ---- CSV 导入 ----

if st.session_state.get("show_import"):
    with st.container():
        st.subheader("📥 CSV 批量导入")
        st.caption("CSV 格式：question, standard_answer, difficulty, kp_name, tags")
        st.caption("difficulty: easy/medium/hard，kp_name 需与知识点目录中的名称匹配，可为空")

        uploaded_file = st.file_uploader("选择 CSV 文件", type=["csv"])
        if uploaded_file:
            try:
                df_import = pd.read_csv(uploaded_file)
                st.write(f"检测到 {len(df_import)} 行数据")
                st.dataframe(df_import.head(5), use_container_width=True)

                if st.button("✅ 确认导入", type="primary"):
                    kp_name_map = {kp["kp_name"]: kp["kp_id"] for kp in all_kps}
                    imported = 0
                    for _, row in df_import.iterrows():
                        q = str(row.get("question", "")).strip()
                        a = str(row.get("standard_answer", "")).strip()
                        if not q or not a:
                            continue
                        d = str(row.get("difficulty", "medium")).strip()
                        if d not in ("easy", "medium", "hard"):
                            d = "medium"
                        kp_name = str(row.get("kp_name", "")).strip()
                        kp_id = kp_name_map.get(kp_name, "")
                        tags = str(row.get("tags", "")).strip()
                        add_bank_question(q, a, d, kp_id or None, tags)
                        imported += 1

                    st.success(f"成功导入 {imported} 题！")
                    st.session_state.show_import = False
                    st.rerun()
            except Exception as e:
                st.error(f"CSV 解析失败: {e}")

        if st.button("❌ 取消导入"):
            st.session_state.show_import = False
            st.rerun()

# ---- 题目列表 ----

st.divider()
st.subheader("📋 题目列表")

# 分页
page_size = 20
if "bank_page" not in st.session_state:
    st.session_state.bank_page = 0

total_count = get_bank_question_count(search_text, diff_filter, kp_filter)
total_pages = max(1, (total_count + page_size - 1) // page_size)
offset = st.session_state.bank_page * page_size

questions = get_bank_questions(search_text, diff_filter, kp_filter, page_size, offset)

if not questions:
    st.info("暂无题目。点击「添加题目」创建第一道题，或点击「导入CSV」批量导入。")
else:
    # 分页导航
    col_prev, col_page, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("◀ 上一页", disabled=(st.session_state.bank_page == 0)):
            st.session_state.bank_page -= 1
            st.rerun()
    with col_page:
        st.caption(f"第 {st.session_state.bank_page + 1}/{total_pages} 页，共 {total_count} 题")
    with col_next:
        if st.button("下一页 ▶", disabled=(st.session_state.bank_page >= total_pages - 1)):
            st.session_state.bank_page += 1
            st.rerun()

    diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}

    for q in questions:
        d_emoji = diff_emoji.get(q["difficulty"], "")
        kp_info = f" · {q['kp_name']}" if q.get("kp_name") else ""

        with st.expander(f"{d_emoji} {q['question'][:80]}..." if len(q.get("question", "")) > 80
                         else f"{d_emoji} {q['question']}"):
            st.write(f"**题目**: {q['question']}")
            st.write(f"**标准答案**: {q['standard_answer']}")
            st.caption(f"难度: {q['difficulty']}{kp_info} · 标签: {q.get('tags', '') or '无'} · "
                       f"使用: {q.get('usage_count', 0)}次 · 正确: {q.get('correct_count', 0)}次")

            # 编辑/删除
            col_edit, col_delete = st.columns([1, 1])
            with col_edit:
                edit_key = f"edit_{q['id']}"
                if st.button("✏️ 编辑", key=f"edit_btn_{q['id']}"):
                    st.session_state[edit_key] = True

            with col_delete:
                if st.button("🗑️ 删除", key=f"del_{q['id']}"):
                    delete_bank_question(q["id"])
                    st.success("已删除")
                    st.rerun()

            # 编辑表单
            edit_key = f"edit_{q['id']}"
            if st.session_state.get(edit_key):
                with st.form(key=f"edit_form_{q['id']}"):
                    edit_q = st.text_area("题目", value=q["question"], height=80)
                    edit_a = st.text_area("标准答案", value=q["standard_answer"], height=100)
                    ce1, ce2, ce3 = st.columns(3)
                    with ce1:
                        diff_idx = {"easy": 0, "medium": 1, "hard": 2}.get(q["difficulty"], 1)
                        edit_diff = st.selectbox("难度", ["easy", "medium", "hard"], index=diff_idx,
                                                 format_func=lambda x: {"easy": "简单", "medium": "中等", "hard": "困难"}[x])
                    with ce2:
                        curr_kp_idx = next((i for i, kp in enumerate(kp_raw) if kp == q.get("kp_id")), 0)
                        edit_kp_idx = st.selectbox("知识点", range(len(kp_labels)), index=curr_kp_idx,
                                                   format_func=lambda i: kp_labels[i])
                        edit_kp_id = kp_raw[edit_kp_idx]
                    with ce3:
                        edit_tags = st.text_input("标签", value=q.get("tags", ""))

                    col_save, col_cancel_edit = st.columns(2)
                    with col_save:
                        if st.form_submit_button("💾 保存修改", use_container_width=True):
                            update_bank_question(q["id"],
                                                 question=edit_q.strip(),
                                                 standard_answer=edit_a.strip(),
                                                 difficulty=edit_diff,
                                                 kp_id=edit_kp_id,
                                                 tags=edit_tags)
                            st.session_state[edit_key] = False
                            st.success("已更新！")
                            st.rerun()
                    with col_cancel_edit:
                        if st.form_submit_button("取消", use_container_width=True):
                            st.session_state[edit_key] = False
                            st.rerun()
