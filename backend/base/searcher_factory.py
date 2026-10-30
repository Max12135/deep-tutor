"""Concise provider-agnostic web search factory using LangChain community utilities.

This implementation leverages lightweight wrappers shipped with LangChain
instead of hand-written HTTP code. It supports Bing, Tavily, and Serper.dev.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Union, cast
from langchain_core.documents import Document
from .dataclass import SearchResult
from pydantic import BaseModel
from omegaconf import OmegaConf, DictConfig
from utils.config import ensure_config_dict


class BingChinaSearch:
    """cn.bing.com 网页搜索（HTML 解析实现，无需 API Key，国内可直接访问）。

    返回格式与 DuckDuckGoSearchAPIWrapper.results() 对齐：
    [{"title": ..., "link": ..., "snippet": ...}, ...]
    """

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    def results(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://cn.bing.com/search?q={encoded}&count={max_results * 2}&setlang=zh-hans"
            req = urllib.request.Request(url, headers=self._HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                page = resp.read().decode("utf-8", errors="ignore")

            results: List[Dict[str, Any]] = []
            # 每个自然结果位于 <li class="b_algo"> ... </li> 块中
            blocks = re.split(r'<li class="b_algo', page)[1:]
            for block in blocks:
                if len(results) >= max_results:
                    break
                link_match = re.search(
                    r'<h2[^>]*>\s*<a[^>]+href="(http[^"]+)"[^>]*>(.*?)</a>',
                    block,
                    re.DOTALL,
                )
                if not link_match:
                    continue
                link = html.unescape(link_match.group(1))
                title = re.sub(r"<[^>]+>", "", link_match.group(2))
                snippet = ""
                snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL)
                if snippet_match:
                    snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1))
                results.append({
                    "title": html.unescape(title).strip(),
                    "link": link.strip(),
                    "snippet": html.unescape(snippet).strip(),
                })
            if not results:
                print(f"[BingChinaSearch] 未解析到搜索结果: {query}")
            return results
        except Exception as e:
            print(f"[BingChinaSearch] 搜索失败: {e}")
            return []


class SearcherFactory:
    """Create concise searchers backed by LangChain community utilities."""

    @staticmethod
    def create(provider: str, **kwargs: Any) -> BaseModel:
        p = (provider or "").strip().lower()
        if p in {"bing_cn", "bing-china", "cn-bing"}:
            # 国内可直连的必应中国网页搜索（无需 API Key）
            wrapper = BingChinaSearch()
        elif p in {"duckduckgo", "duck-duck-go"}:
            from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
            wrapper = DuckDuckGoSearchAPIWrapper(region="cn-zh", safesearch="moderate")
        elif p in {"serper", "serper.dev", "google-serper"}:
            from langchain_community.utilities import GoogleSerperAPIWrapper
            wrapper = GoogleSerperAPIWrapper()
        elif p in {"bing", "microsoft-bing"}:
            from langchain_community.utilities import BingSearchAPIWrapper
            bing_subscription_key = kwargs.get("bing_subscription_key", None)
            bing_search_url = kwargs.get("bing_search_url", None)
            assert bing_subscription_key is not None, "bing_subscription_key is required for BingSearchAPIWrapper"
            assert bing_search_url is not None, "bing_search_url is required for BingSearchAPIWrapper"
            wrapper = BingSearchAPIWrapper(bing_subscription_key=bing_subscription_key, bing_search_url=bing_search_url)
        elif p in {"brave", "brave-search"}:
            from langchain_community.utilities import BraveSearchWrapper
            wrapper = BraveSearchWrapper()
        else:
            raise ValueError("Unsupported search provider. Choose from {'bing_cn', 'bing', 'serper', 'duckduckgo', 'brave', 'searx', 'you'}.")
        return wrapper


class WebDocumentLoader:

    @staticmethod
    def invoke(urls: List[str], loader_type: str = "web") -> List[Document]:
        """Load documents from the provided URLs using the specified loader."""
        if not urls:
            return []
        if loader_type == "docling":
            from langchain_docling import DoclingLoader
            loader = DoclingLoader(urls)
        elif loader_type == "web":
            from langchain_community.document_loaders import WebBaseLoader
            import bs4
            # bs4_strainer = bs4.SoupStrainer(class_=("post-title", "post-header", "post-content"))
            # loader = WebBaseLoader(urls, bs_kwargs={"parse_only": bs4_strainer},)
            # 'verify':False, 
            loader = WebBaseLoader(urls, requests_kwargs={'timeout':10})
        try:
            documents = loader.load()
        except Exception as e:
            print(f"Error loading documents from URLs: {e}")
            documents = []
        return documents


class SearchRunner:
    """Manager to perform searches using different providers."""

    # 单篇网页正文的最大入上下文长度（字符）
    _MAX_DOC_CHARS = 4000

    def __init__(
            self, 
            searcher: BaseModel,
            loader_type: str = "web",
            max_search_results: int = 5,
            **kwargs: Any
        ) -> None:
        self.searcher = searcher
        self.loader_type = loader_type
        self.max_search_results = max_search_results

    @staticmethod
    def from_config(
            config: Union[DictConfig, Dict[str, Any]],
        ) -> "SearchRunner":
  
        config_dict = ensure_config_dict(config)
        searcher = SearcherFactory.create(
            provider=config_dict.get("search", {}).get("provider", "duckduckgo"),
            **config_dict,
        )
        return SearchRunner(
            searcher=searcher,
            loader_type=config_dict.get("search", {}).get("loader_type", "web"),
            max_search_results=config_dict.get("search", {}).get("max_results", 5),
        )

    def invoke(self, query: str) -> List[SearchResult]:
        """Perform a search and return structured results.

        对外部资源做三件事，避免把噪声灌进 RAG：
        - 按归一化 URL 与内容前缀去重（必应常返回同站多条结果，如 dupe 首页）
        - 过短正文（反爬拦截页）回退为搜索摘要
        - 单篇正文截断，避免单个长页面（如时政长文）独占上下文
        """
        raw_results = self.searcher.results(query, max_results=self.max_search_results)

        structured_results: List[SearchResult] = []
        seen_urls: set = set()
        seen_contents: set = set()
        for item in raw_results:
            link = item.get("link", "")
            if not link:
                continue
            url_key = self._normalize_url(link)
            if url_key in seen_urls:
                continue
            document = self._load_single_document(link, item)
            content = (document.page_content if document is not None else (item.get("snippet") or "")).strip()
            if not content:
                continue
            if len(content) > self._MAX_DOC_CHARS:
                content = content[: self._MAX_DOC_CHARS]
                if document is not None:
                    document.page_content = content
            content_key = content[:300]
            if content_key in seen_contents:
                continue
            seen_urls.add(url_key)
            seen_contents.add(content_key)
            structured_results.append(
                SearchResult(
                    title=item.get("title", ""),
                    link=link,
                    content=content,
                    snippet=item.get("snippet", None),
                    document=document,
                )
            )

        return structured_results

    @staticmethod
    def _normalize_url(url: str) -> str:
        """URL 归一化用于去重：去协议、www.、fragment 与末尾斜杠。"""
        u = (url or "").strip().lower().split("#", 1)[0]
        u = re.sub(r"^https?://", "", u)
        u = re.sub(r"^www\.", "", u)
        return u.rstrip("/")

    def _load_single_document(self, url: str, item: Dict[str, Any]) -> Document | None:
        """逐 URL 加载网页；正文过短或失败时用搜索摘要兜底，保证 RAG 上下文不空。"""
        try:
            docs = WebDocumentLoader.invoke([url], loader_type=self.loader_type)
        except Exception:
            docs = []
        page = (docs[0].page_content or "").strip() if docs else ""
        snippet = (item.get("snippet") or "").strip()
        # 正文过短多为反爬/拦截页（如百度百科 403 只剩几个字），此时摘要信息量更大
        if page and (len(page) >= 200 or len(page) >= len(snippet)):
            return docs[0]
        if snippet:
            return Document(
                page_content=snippet,
                metadata={"title": item.get("title", ""), "source": url},
            )
        if page:
            return docs[0]
        return None


if __name__ == "__main__":
    searcher = SearcherFactory.create(
        provider="duckduckgo",
    )

    searcher_runner = SearchRunner(
        searcher=searcher,
        loader_type="web",
        max_search_results=5,
    )
    results = searcher_runner.invoke("LangChain community utilities")
    print(results)