"""向量化模块 - BGE-small-zh 中文嵌入"""
import os

# 离线模式：禁止连接 HuggingFace Hub
os.environ["HF_HUB_OFFLINE"] = "1"

from sentence_transformers import SentenceTransformer
import numpy as np

# 模型本地路径：优先用项目内的 models/bge-small-zh-v1.5
_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "bge-small-zh-v1.5")
if os.path.isdir(_MODEL_DIR):
    MODEL_NAME = _MODEL_DIR
else:
    MODEL_NAME = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DIM = 512


class Embedder:
    def __init__(self, model_name: str = MODEL_NAME, device: str = None):
        if device is None:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = SentenceTransformer(model_name, device=device)
        self.dim = self.model.get_embedding_dimension()

    def encode(self, texts: list[str], show_progress: bool = True):
        """将文本列表转换为向量，每条文本加 instruction 前缀以提升质量"""
        prefixed = [f"为这个句子生成表示以用于检索相关文章：{t}" for t in texts]
        embeddings = self.model.encode(
            prefixed,
            show_progress_bar=show_progress,
            normalize_embeddings=True,
            batch_size=32,
        )
        return np.array(embeddings, dtype=np.float32)

    def encode_query(self, query: str):
        """查询向量化"""
        prefixed = f"为这个句子生成表示以用于检索相关文章：{query}"
        vec = self.model.encode([prefixed], normalize_embeddings=True)
        return np.array(vec, dtype=np.float32)
