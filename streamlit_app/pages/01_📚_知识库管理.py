"""知识库管理 - 文档上传、查看、索引管理"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from pathlib import Path

from streamlit_app.shared import get_embedder, get_retriever, init_session, is_teacher, render_profile_selector

init_session()
render_profile_selector()

if not is_teacher():
    st.warning("此功能仅教师可用，请切换到教师身份。")
    st.stop()

st.title("📚 知识库管理")


def do_rebuild():
    """核心：加载文档 → 分块 → 向量化 → 建索引"""
    with st.status("处理文档...", expanded=True) as status:
        status.update(label="解析文档...")
        from core.loader import load_documents
        docs, stats = load_documents()

        status.update(label=f"分块中... ({len(docs)} 篇文档)")
        from core.splitter import split_documents
        nodes = split_documents(docs)

        status.update(label=f"向量化中... ({len(nodes)} 个块)")
        embedder = get_embedder()
        texts = [n.text if hasattr(n, 'text') else str(n) for n in nodes]
        embeddings = embedder.encode(texts)

        status.update(label="构建 FAISS 索引...")
        from core.indexer import build_index
        node_ids = [n.node_id if hasattr(n, 'node_id') else n.get('node_id', '') for n in nodes]
        build_index(embeddings, node_ids, nodes)

        status.update(label="更新检索器...")
        retriever = get_retriever()
        retriever.set_nodes(nodes)
        retriever.reload()
        st.cache_resource.clear()

        status.update(label="完成!", state="complete")

    st.success(f"索引构建完成！{len(set(d.metadata.get('file_name','') for d in docs))} 个文件，{len(docs)} 页，{len(nodes)} 个文本块")


# --- 上传区域 ---
st.subheader("📤 上传文档")
uploaded_files = st.file_uploader(
    "拖拽或点击上传 PDF / Word / TXT 文件",
    type=["pdf", "docx", "txt"],
    accept_multiple_files=True,
)

if uploaded_files:
    data_dir = Path("data/documents")
    data_dir.mkdir(parents=True, exist_ok=True)

    for f in uploaded_files:
        filepath = data_dir / f.name
        with open(filepath, "wb") as fp:
            fp.write(f.getbuffer())

    st.success(f"已上传 {len(uploaded_files)} 个文件")

    if st.button("🔄 处理文档并重建索引", type="primary"):
        do_rebuild()

# --- 已导入文档列表 ---
st.subheader("📄 已导入文档")

from core.indexer import index_exists, load_meta
data_dir = Path("data/documents")
if data_dir.exists():
    files = sorted(data_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    real_files = [fp for fp in files if fp.suffix.lower() in [".pdf", ".docx", ".txt"]]

    if not real_files:
        st.info("暂无文档，请上传并处理")
    else:
        node_ids = load_meta() if index_exists() else []
        for fp in real_files:
            size_mb = fp.stat().st_size / (1024 * 1024)
            col1, col2, col3 = st.columns([4, 2, 1])
            with col1:
                st.write(f"📄 {fp.name}")
            with col2:
                st.write(f"{size_mb:.1f} MB")
            with col3:
                if st.button("🗑️", key=f"del_{fp.name}"):
                    fp.unlink()
                    st.warning(f"已删除 {fp.name}（需重建索引以同步）")

        st.caption(f"FAISS 索引: {len(node_ids)} 个向量块" if index_exists() else "尚未建立索引")

        if st.button("🔄 重建索引", type="primary"):
            do_rebuild()
else:
    st.info("暂无文档，请上传并处理")
