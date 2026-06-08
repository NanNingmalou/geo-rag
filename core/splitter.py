"""文本分块器 - 简单中文字符计数分块"""
from llama_index.core.schema import Document, TextNode

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """按字符数切分中文文本，优先在句末断句"""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # 在 chunk_size 范围内尽量找句末断句点
            for lookback in range(min(100, end - start)):
                pos = end - lookback
                if pos > start and text[pos - 1] in "。！？\n":
                    end = pos
                    break
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = end - chunk_overlap if end < len(text) else len(text)
        # 确保前进
        if start <= 0 or start >= len(text) - 1:
            break
    return chunks


def split_documents(documents: list[Document], chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> list[TextNode]:
    """逐文档切分，过滤纯标点/空白块"""
    from llama_index.core import Settings
    nodes = []
    for doc in documents:
        text = doc.text
        if not text or not text.strip():
            continue
        chunks = _chunk_text(text, chunk_size, chunk_overlap)
        for i, chunk in enumerate(chunks):
            # 过滤纯标点/空白块
            cleaned = chunk.strip().strip("。；，、：！？ \n\r\t_-")
            if len(cleaned) < 20:
                continue
            node = TextNode(
                text=chunk,
                metadata={**doc.metadata, "chunk_index": i},
            )
            nodes.append(node)
    return nodes
