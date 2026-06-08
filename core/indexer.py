"""FAISS 索引管理 - 构建 / 加载 / 增量更新"""
import os
import json
import numpy as np
import faiss

INDEX_PATH = "data/index.faiss"
META_PATH = "data/index_meta.json"
NODES_PATH = "data/nodes.json"


def build_index(embeddings: np.ndarray, node_ids: list[str], nodes=None):
    """构建 FAISS IVF+Flat 索引并持久化，同时保存节点文本"""
    dim = embeddings.shape[1]
    nlist = min(128, max(4, int(np.sqrt(len(node_ids)))))

    quantizer = faiss.IndexFlatIP(dim)
    index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)

    if not index.is_trained:
        index.train(embeddings)
    index.add(embeddings)

    faiss.write_index(index, INDEX_PATH)
    save_meta(node_ids)
    if nodes is not None:
        save_nodes(nodes)
    return index


def load_index():
    """加载已有索引"""
    if not os.path.exists(INDEX_PATH):
        return None, []
    index = faiss.read_index(INDEX_PATH)
    node_ids = load_meta()
    return index, node_ids


def load_nodes():
    """加载节点文本数据 {node_id: {text, file_name}}"""
    if not os.path.exists(NODES_PATH):
        return {}
    with open(NODES_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return raw


def save_nodes(nodes):
    """保存节点文本到 JSON"""
    data = {}
    for n in nodes:
        meta = n.metadata if hasattr(n, "metadata") else {}
        data[n.node_id] = {
            "text": n.text if hasattr(n, "text") else str(n),
            "file_name": str(meta.get("file_name", "")),
            "page_label": str(meta.get("page_label", "")),
        }
    with open(NODES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def save_meta(node_ids: list[str]):
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump({"node_ids": node_ids, "count": len(node_ids)}, f, ensure_ascii=False)


def load_meta():
    if not os.path.exists(META_PATH):
        return []
    with open(META_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("node_ids", [])


def index_exists():
    return os.path.exists(INDEX_PATH) and os.path.exists(META_PATH)
