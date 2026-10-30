import os
import hashlib
import logging
import threading
from typing import List, Optional, Dict, Any, Union
from omegaconf import DictConfig

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_text_splitters.base import TextSplitter

from base.dataclass import SearchResult
from base.embedder_factory import EmbedderFactory
from base.searcher_factory import SearcherFactory, SearchRunner
from base.rag_factory import TextSplitterFactory, VectorStoreFactory
from utils.config import ensure_config_dict

logger = logging.getLogger(__name__)

# 同进程内可能有多个线程并发写同一个向量库（知识点草稿阶段用线程池并发检索），
# 用模块级锁串行化写入，避免 Chroma 并发写导致丢写或数据错乱。
_VECTORSTORE_WRITE_LOCK = threading.Lock()


class SearchRagManager:

    # 单个知识点注入 LLM 的外部资源总长度上限（字符）
    _MAX_CONTEXT_CHARS = 6000

    def __init__(
        self, 
        embedder: Embeddings,
        text_splitter: Optional[TextSplitter] = None,
        vectorstore: Optional[VectorStore] = None,
        search_runner: Optional[SearchRunner] = None,
        max_retrieval_results: int = 5,
    ):
        self.embedder = embedder
        self.text_splitter = text_splitter
        self.vectorstore = vectorstore
        self.search_runner = search_runner
        self.max_retrieval_results = max_retrieval_results

    @staticmethod
    def from_config(
        config: Union[DictConfig, Dict[str, Any]],
    ) -> "SearchRagManager":
        config = ensure_config_dict(config)
        # 配置键为 embedding（兼容旧键名 embedder）；加载失败时回退到旧英文模型
        embedder_config = config.get("embedding", None) or config.get("embedder", {}) or {}
        embedder_model = embedder_config.get("model_name", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        embedder_provider = embedder_config.get("provider", "huggingface")
        try:
            embedder = EmbedderFactory.create(
                model=embedder_model,
                model_provider=embedder_provider,
            )
        except Exception as e:
            logger.warning(f"Embedding 模型 {embedder_model} 加载失败，回退到 all-mpnet-base-v2: {e}")
            embedder = EmbedderFactory.create(
                model="sentence-transformers/all-mpnet-base-v2",
                model_provider="huggingface",
            )

        text_splitter = TextSplitterFactory.create(
            splitter_type=config.get("rag", {}).get("text_splitter_type", "recursive_character"),
            chunk_size=config.get("rag", {}).get("chunk_size", 1000),
            chunk_overlap=config.get("rag", {}).get("chunk_overlap", 0),
        )

        vectorstore = VectorStoreFactory.create(
            vectorstore_type=config.get("vectorstore", {}).get("type", "chroma"),
            collection_name=config.get("vectorstore", {}).get("collection_name", "default_collection"),
            persist_directory=config.get("vectorstore", {}).get("persist_directory", "./data/vectorstore"),
            embedder=embedder,
        )

        search_runner = SearchRunner.from_config(
            config=config
        )

        return SearchRagManager(
            embedder=embedder,
            text_splitter=text_splitter,
            vectorstore=vectorstore,
            search_runner=search_runner,
            max_retrieval_results=config.get("rag", {}).get("num_retrieval_results", 5),
        )


    def search(self, query: str) -> List[SearchResult]:
        if not self.search_runner:
            raise ValueError("SearcherRunner is not initialized.")
        results = self.search_runner.invoke(query)
        return results

    def add_documents(self, documents: List[Document]) -> None:
        if len(documents) == 0:
            logger.warning("No documents to add to the vectorstore.")
            return
        if not self.vectorstore:
            raise ValueError("VectorStore is not initialized.")
        documents = [doc for doc in documents if len(doc.page_content.strip()) > 0]
        if self.text_splitter:
            split_docs = self.text_splitter.split_documents(documents)
        else:
            split_docs = documents
        batch_size = 3000
        # 写入向量库是共享资源操作：用锁保证同一时刻只有一个线程在写。
        with _VECTORSTORE_WRITE_LOCK:
            for i in range(0, len(split_docs), batch_size):
                batch = split_docs[i:i + batch_size]
                # 用内容哈希作为 id（批内先去重），重复内容走 upsert 覆盖而非追加，
                # 避免每次检索都把同一批网页重复写库导致向量库无限膨胀。
                uniq = {}
                for doc in batch:
                    uniq.setdefault(hashlib.sha1(doc.page_content.encode("utf-8")).hexdigest(), doc)
                self.vectorstore.add_documents(list(uniq.values()), ids=list(uniq.keys()))
                logger.info(f"Added batch {i//batch_size + 1}")
        # self.vectorstore.add_documents(split_docs, embedding_function=self.embedder)
        logger.info(f"Added {len(split_docs)} documents to the vectorstore.")

    def retrieve(self, query: str, k: Optional[int] = None) -> List[Document]:
        k = k or self.max_retrieval_results
        if not self.vectorstore:
            raise ValueError("VectorStore is not initialized.")
        retrieval = self.vectorstore.similarity_search(query, k=k)
        return retrieval

    def invoke(self, query: str, fresh_only: bool = False) -> List[Document]:
        """检索并写入向量库，返回用于 LLM 上下文的片段。

        fresh_only=True 时只返回"本次检索到的新文档"切分后的片段，不做全局相似度检索。
        原因：向量库是跨目标/会话共享累积的，全局检索会命中别的目标的高相似旧内容——
        实测"思维定势"查询会把同一篇时政长文的多个片段全部顶到最前面，导致生成内容跑偏。
        """
        results = self.search(query)
        documents = [res.document for res in results if res.document is not None]
        self.add_documents(documents=documents)
        if fresh_only:
            return self._chunk_fresh_documents(documents)
        retrieved_docs = self.retrieve(query)
        return retrieved_docs

    def _chunk_fresh_documents(self, documents: List[Document]) -> List[Document]:
        """把本次检索到的文档切分、去重，并按总长度上限返回片段。"""
        docs = [d for d in documents if d and (d.page_content or "").strip()]
        if not docs:
            return []
        chunks = self.text_splitter.split_documents(docs) if self.text_splitter else docs
        out: List[Document] = []
        seen: set = set()
        total = 0
        for chunk in chunks:
            text = (chunk.page_content or "").strip()
            if not text or text in seen:
                continue
            if total + len(text) > self._MAX_CONTEXT_CHARS:
                break
            seen.add(text)
            out.append(chunk)
            total += len(text)
        return out


def format_docs(docs: List[Document]) -> str:
    formatted_chunks: List[str] = []
    for idx, doc in enumerate(docs):
        title = doc.metadata.get("title") if doc.metadata else None
        source = doc.metadata.get("source") if doc.metadata else None
        header_parts = [f"[{idx}]"]
        if title:
            header_parts.append(title)
        if source:
            header_parts.append(f"Source: {source}")
        header = " | ".join(header_parts)
        body = doc.page_content.strip()
        formatted_chunks.append(f"{header}\n{body}")
    return "\n\n".join(formatted_chunks)



if __name__ == "__main__":
    # python -m base.search_rag
    embedder = EmbedderFactory.create(
        model="sentence-transformers/all-mpnet-base-v2",
        model_provider="huggingface"
    )

    searcher = SearcherFactory.create(
        provider="duckduckgo",
        max_results=5,
    )

    search_runner = SearchRunner(
        searcher=searcher,
        loader_type="web",
        max_search_results=5,
    )

    text_splitter = TextSplitterFactory.create(
        splitter_type="recursive_character",
        chunk_size=1000,
        chunk_overlap=0,
    )

    vectorstore = VectorStoreFactory.create(
        vectorstore_type="chroma",
        collection_name="example_collection",
        persist_directory="./data/vectorstore",
        embedder=embedder,
    )

    rag_manager = SearchRagManager(
        embedder=embedder,
        text_splitter=text_splitter,
        vectorstore=vectorstore,
        search_runner=search_runner,
    )

    from config import default_config
    rag_manager = SearchRagManager.from_config(default_config)

    results = rag_manager.search("LangChain community utilities")
    print(f"Retrieved {len(results)} search results.")
    documents = [res.document for res in results if res.document is not None]
    rag_manager.add_documents(documents=documents)

    retrieved_docs = rag_manager.retrieve("LangChain community utilities", k=5)
    print(f"Retrieved {len(retrieved_docs)} documents from vectorstore.")
    print(format_docs(retrieved_docs))