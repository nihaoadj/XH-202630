import os
import json
from typing import List
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

from app.config import get_settings, resolve_backend_path


def load_documents(kb_dir: str = None) -> List[Document]:
    """加载知识库目录中的 Markdown / TXT 文件并切片"""
    if kb_dir is None:
        kb_dir = get_settings().knowledge_base_dir

    docs = []
    kb_path = resolve_backend_path(kb_dir)
    for root, _, files in os.walk(kb_path):
        for file in files:
            if file.endswith((".md", ".txt")):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                docs.append(Document(page_content=text, metadata={"source": path}))
    return docs


def chunk_documents(documents: List[Document], chunk_size=500, chunk_overlap=50) -> List[Document]:
    """对文档进行语义切片"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", " ", ""],
    )
    return splitter.split_documents(documents)


def load_metadata(kb_dir: str = None) -> dict:
    """加载知识库元数据"""
    if kb_dir is None:
        kb_dir = get_settings().knowledge_base_dir
    meta_path = resolve_backend_path(os.path.join(kb_dir, "metadata.json"))
    if not os.path.exists(meta_path):
        return {}
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)
