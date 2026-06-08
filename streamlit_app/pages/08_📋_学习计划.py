"""学习计划 - LLM 生成的结构化复习计划，逐项追踪进度"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd

from streamlit_app.shared import init_session, get_active_llm, render_profile_selector
from utils.db import (
    get_active_plan, get_plan_items, complete_plan_item,
    skip_plan_item, reset_plan_item, get_plan_history,
)

init_session()
render_profile_selector()

st.title("📋 学习计划")

llm = get_active_llm()

# ---- 获取当前计划 ----

plan, items = get_active_plan()

# ---- 无计划时显示引导 ----

if plan is None:
    st.info("📋 还没有学习计划。系统会根据你的自测数据，智能生成一个按优先级排序的复习计划。")

    if llm is None:
        st.warning("请先在 ⚙️ 系统设置中配置 LLM")
    else:
        if st.button("🧠 生成我的学习计划", type="primary"):
            with st.spinner("分析你的学习数据，生成个性化计划..."):
                from utils.knowledge_points import generate_learning_plan
                result = generate_learning_plan(llm)
                if result.get("error"):
                    st.error(result["error"])
                elif result.get("plan_id"):
                    st.success(f"计划已生成！共 {len(result['items'])} 个步骤")
                    st.rerun()
                else:
                    st.warning("数据不足，请先完成一些自测题目后再生成计划")

    # 历史计划
    history = get_plan_history()
    if history:
        st.divider()
        st.subheader("📜 历史计划")
        for h in history:
            with st.expander(f"{h['created_at'][:10]} — {h['completed_items']}/{h['total_items']} 完成"):
                h_items = get_plan_items(h["id"])
                for item in h_items:
                    emoji = "✅" if item["status"] == "completed" else ("⏭️" if item["status"] == "skipped" else "⬜")
                    st.write(f"{emoji} {item['description']}")

    st.stop()


# ---- 活跃计划展示 ----

# 进度统计
total = len(items)
completed = sum(1 for i in items if i["status"] == "completed")
skipped = sum(1 for i in items if i["status"] == "skipped")
pending = total - completed - skipped

col_head, col_regen = st.columns([3, 1])
with col_head:
    st.subheader(f"📋 当前学习计划 · {plan['created_at'][:10]} 生成")
with col_regen:
    if llm and st.button("🔄 重新生成", use_container_width=True):
        with st.spinner("基于最新数据重新生成计划..."):
            from utils.knowledge_points import generate_learning_plan
            result = generate_learning_plan(llm)
            if result.get("error"):
                st.error(result["error"])
            else:
                st.success(f"新计划已生成！共 {len(result['items'])} 个步骤")
                st.rerun()

# 进度条
progress_pct = completed / total if total > 0 else 0
st.progress(progress_pct)
col1, col2, col3 = st.columns(3)
col1.metric("已完成", completed)
col2.metric("进行中", pending)
col3.metric("已跳过", skipped)

st.divider()

# 计划项列表
action_icons = {
    "review": "📖",
    "practice": "✍️",
    "retry_wrong": "🔁",
    "read": "📄",
}
action_labels = {
    "review": "回顾教材",
    "practice": "做练习题",
    "retry_wrong": "重做错题",
    "read": "阅读资料",
}

for item in items:
    status = item["status"]
    icon = action_icons.get(item.get("action_type", "review"), "📖")
    action_label = action_labels.get(item.get("action_type", "review"), "")
    kp_info = f" · {item.get('domain_name', '')} · {item.get('chapter_name', '')}" if item.get("domain_name") else ""
    reason_text = f"\n\n💡 *{item['reason']}*" if item.get("reason") else ""

    if status == "completed":
        # 已完成项：折叠显示
        with st.expander(f"✅ {item['description']} {kp_info}", expanded=False):
            st.caption(f"{icon} {action_label}{reason_text}")
            if st.button("🔄 重置", key=f"reset_{item['id']}"):
                reset_plan_item(item["id"])
                st.rerun()
    elif status == "skipped":
        with st.expander(f"⏭️ {item['description']} {kp_info}", expanded=False):
            st.caption(f"{icon} {action_label}{reason_text}")
            if st.button("🔄 恢复", key=f"restore_{item['id']}"):
                reset_plan_item(item["id"])
                st.rerun()
    else:
        # 待完成项：完整展示
        with st.container():
            st.markdown(f"### {item['order_index']}. {item['description']}")
            st.caption(f"{icon} {action_label}{kp_info}{reason_text}")

            col_act, col_skip = st.columns([1, 1])
            with col_act:
                if st.button("✅ 标记完成", key=f"done_{item['id']}", use_container_width=True):
                    complete_plan_item(item["id"])
                    st.rerun()
            with col_skip:
                if st.button("⏭️ 跳过", key=f"skip_{item['id']}", use_container_width=True):
                    skip_plan_item(item["id"])
                    st.rerun()
            st.divider()

# ---- 历史计划 ----

history = get_plan_history()
if history:
    st.subheader("📜 历史计划")
    for h in history:
        with st.expander(f"{h['created_at'][:10]} — {h['completed_items']}/{h['total_items']} 完成"):
            h_items = get_plan_items(h["id"])
            for item in h_items:
                emoji = "✅" if item["status"] == "completed" else ("⏭️" if item["status"] == "skipped" else "⬜")
                st.write(f"{emoji} {item['order_index']}. {item['description']}")
