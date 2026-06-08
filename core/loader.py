"""文档加载器 - 支持 PDF / Word / TXT"""
from pathlib import Path
from llama_index.core import SimpleDirectoryReader


def load_documents(directory: str = "data/documents"):
    """加载目录下所有支持的文档，返回 (文档列表, 统计信息)"""
    Path(directory).mkdir(parents=True, exist_ok=True)

    stats = {"pdf": 0, "docx": 0, "txt": 0, "failed": []}
    documents = []

    reader = SimpleDirectoryReader(
        input_dir=directory,
        required_exts=[".pdf", ".docx", ".txt"],
        recursive=True,
    )
    docs = reader.load_data(show_progress=True)

    for doc in docs:
        ext = Path(doc.metadata.get("file_name", "")).suffix.lower().lstrip(".")
        if ext in stats:
            stats[ext] += 1
        else:
            stats["failed"].append(doc.metadata.get("file_name", ""))
        documents.append(doc)

    return documents, stats


def load_single_file(filepath: str):
    """加载单个文件"""
    reader = SimpleDirectoryReader(input_files=[filepath])
    return reader.load_data()
