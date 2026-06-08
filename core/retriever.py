"""检索器 - 向量检索 + 片段返回"""
import numpy as np
from core.embedder import Embedder
from core.indexer import load_index, load_nodes


class _NodeProxy:
    """轻量节点代理，避免完整 Node 对象的序列化问题"""
    def __init__(self, node_id: str, text: str, metadata: dict):
        self.node_id = node_id
        self.text = text
        self.metadata = metadata


class Retriever:
    def __init__(self, embedder: Embedder, top_k: int = 2, threshold: float = 0.6,
                 quality_weight: float = 0.5):
        self.embedder = embedder
        self.top_k = top_k
        self.threshold = threshold
        self.quality_weight = quality_weight  # 0=关闭质量反馈, 1=最强
        self.index = None
        self.node_ids = []
        self._node_map = {}  # node_id -> _NodeProxy
        self.reload()

    def reload(self):
        self.index, self.node_ids = load_index()
        if self.index is not None:
            self._node_map = {}
            stored = load_nodes()
            for nid in self.node_ids:
                data = stored.get(nid)
                if data:
                    self._node_map[nid] = _NodeProxy(
                        nid, data["text"],
                        {
                            "file_name": data.get("file_name", ""),
                            "page_label": data.get("page_label", ""),
                        },
                    )

    def set_nodes(self, nodes):
        """存储节点映射，供检索时查找原文，兼容 TextNode / _NodeProxy / dict"""
        node_map = {}
        for n in nodes:
            if hasattr(n, "node_id"):
                node_map[n.node_id] = n
            elif isinstance(n, dict):
                node_map[n.get("node_id", n.get("id_", ""))] = n
            elif isinstance(n, str):
                # 如果传入字符串列表，说明是旧版 splitter，跳过
                continue
        self._node_map = node_map

    def retrieve(self, query: str):
        """检索并返回 (片段列表, 分数列表)，支持质量反馈重排序"""
        if self.index is None or self.index.ntotal == 0:
            return [], []

        query_vec = self.embedder.encode_query(query)

        # 扩大召回（3倍），为重排序留空间
        search_k = max(self.top_k * 3, 10)
        distances, indices = self.index.search(query_vec, search_k)

        # 收集候选
        candidates = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.node_ids):
                continue
            if dist < self.threshold:
                continue
            node_id = self.node_ids[idx]
            node = self._node_map.get(node_id)
            if node is not None:
                candidates.append((node, float(dist)))

        if not candidates:
            return [], []

        # 质量重排序
        if self.quality_weight > 0 and len(candidates) > 1:
            try:
                from utils.db import get_chunk_qualities
                chunk_ids = [n.node_id for n, _ in candidates]
                qualities = get_chunk_qualities(chunk_ids)

                # final_score = similarity * (1 + α * (quality - 0.5))
                alpha = self.quality_weight
                reranked = []
                for node, sim in candidates:
                    q = qualities.get(node.node_id, 0.5)
                    final = sim * (1.0 + alpha * (q - 0.5))
                    reranked.append((node, sim, final))
                reranked.sort(key=lambda x: x[2], reverse=True)
                candidates = [(n, s) for n, s, _ in reranked]
            except Exception:
                pass  # 数据库异常时保持原始排序

        # 取 top_k
        results = [n for n, _ in candidates[:self.top_k]]
        scores = [s for _, s in candidates[:self.top_k]]
        return results, scores

    def retrieve_as_context(self, query: str):
        """检索并拼接为 LLM 上下文"""
        nodes, scores = self.retrieve(query)
        if not nodes:
            return "", []
        chunks = []
        for n in nodes:
            if hasattr(n, "text"):
                chunks.append(n.text)
            elif isinstance(n, dict):
                chunks.append(n.get("text", ""))
        return "\n\n---\n\n".join(chunks), nodes
