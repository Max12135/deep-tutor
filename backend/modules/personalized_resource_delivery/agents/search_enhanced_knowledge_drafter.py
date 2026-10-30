from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Optional, List
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, field_validator

from base import BaseAgent
from base.search_rag import SearchRagManager, format_docs
from modules.personalized_resource_delivery.prompts.search_enhanced_knowledge_drafter import (
    search_enhanced_knowledge_drafter_system_prompt,
    search_enhanced_knowledge_drafter_task_prompt,
)
from modules.personalized_resource_delivery.schemas import KnowledgeDraft
from config.loader import default_config

logger = logging.getLogger(__name__)


class KnowledgeDraftPayload(BaseModel):
    learner_profile: Any
    learning_path: Any
    learning_session: Any
    knowledge_points: Any
    knowledge_point: Any
    external_resources: str | None = ""

    @field_validator("learner_profile", "learning_path", "learning_session", "knowledge_points", "knowledge_point")
    @classmethod
    def coerce_jsonish(cls, v: Any) -> Any:
        if isinstance(v, BaseModel):
            return v.model_dump()
        if isinstance(v, Mapping):
            return dict(v)
        if isinstance(v, str):
            return v.strip()
        return v


class SearchEnhancedKnowledgeDrafter(BaseAgent):

    name: str = "SearchEnhancedKnowledgeDrafter"

    def __init__(self, model: Any, *, search_rag_manager: Optional[SearchRagManager] = None, use_search: bool = True):
        super().__init__(model=model, system_prompt=search_enhanced_knowledge_drafter_system_prompt, jsonalize_output=True)
        self.search_rag_manager = search_rag_manager or SearchRagManager.from_config(default_config)
        self.use_search = use_search

    def draft(self, payload: KnowledgeDraftPayload | Mapping[str, Any] | str):
        if not isinstance(payload, KnowledgeDraftPayload):
            payload = KnowledgeDraftPayload.model_validate(payload)
        data = payload.model_dump()
        # 把同会话的其他知识点交给模型，明确"不要与它们重复"（此前这段信息被丢弃）
        data["other_knowledge_points"] = self._other_knowledge_points(data)
        # Optionally enrich external resources using the search RAG manager
        if self.use_search and self.search_rag_manager is not None:
            session = data.get("learning_session") or {}
            session_title = str(session.get("title", "")).strip() or "learning_session"
            knowledge_point = data.get("knowledge_point") or {}
            knowledge_point_name = str(knowledge_point.get('name', '')).strip()
            query = f"{session_title} {knowledge_point_name}".strip()
            # fresh_only=True：只用本次为该知识点检索到的文档，避免全局向量库里
            # 其他目标/会话的高相似旧内容（如时政长文）被顶到上下文最前面。
            docs = self.search_rag_manager.invoke(query, fresh_only=True)
            context = format_docs(docs)
            if context:
                ext = data.get("external_resources") or ""
                data["external_resources"] = f"{ext}{context}"
        raw_output = self.invoke(data, task_prompt=search_enhanced_knowledge_drafter_task_prompt)
        validated_output = KnowledgeDraft.model_validate(raw_output)
        return validated_output.model_dump()

    @staticmethod
    def _other_knowledge_points(data: Mapping[str, Any]) -> List[Any]:
        """返回同会话中除当前知识点以外的其他知识点（用于避免内容重叠）。"""
        kps = data.get("knowledge_points") or []
        if isinstance(kps, str):
            try:
                kps = json.loads(kps)
            except Exception:
                kps = []
        current = data.get("knowledge_point") or {}
        cur_name = str(current.get("name", "") if isinstance(current, dict) else current).strip()
        others: List[Any] = []
        if isinstance(kps, list):
            for kp in kps:
                name = kp.get("name", "") if isinstance(kp, dict) else kp
                if str(name).strip() and str(name).strip() != cur_name:
                    others.append(kp)
        return others

def draft_knowledge_point_with_llm(
    llm,
    learner_profile,
    learning_path,
    learning_session,
    knowledge_points,
    knowledge_point,
    use_search: bool = True,
    *,
    search_rag_manager: Optional[SearchRagManager] = None,
):
    """Draft a single knowledge point using the agent, optionally enriching with a SearchRagManager."""
    drafter = SearchEnhancedKnowledgeDrafter(llm, search_rag_manager=search_rag_manager, use_search=use_search)
    payload = {
        "learner_profile": learner_profile,
        "learning_path": learning_path,
        "learning_session": learning_session,
        "knowledge_points": knowledge_points,
        "knowledge_point": knowledge_point,
    }
    return drafter.draft(payload)


def draft_knowledge_points_with_llm(
    llm,
    learner_profile,
    learning_path,
    learning_session,
    knowledge_points,
    allow_parallel: bool = True,
    use_search: bool = True,
    max_workers: int = 8,
    *,
    search_rag_manager: Optional[SearchRagManager] = None,
):
    """Draft multiple knowledge points in parallel or sequentially using the agent."""
    if isinstance(learning_session, str):
        try:
            learning_session = json.loads(learning_session)
        except Exception:
            pass
    if isinstance(knowledge_points, str):
        try:
            knowledge_points = json.loads(knowledge_points)
        except Exception:
            pass
    if search_rag_manager is None and use_search:
        search_rag_manager = SearchRagManager.from_config(default_config)
    def draft_one(kp):
        return draft_knowledge_point_with_llm(
            llm,
            learner_profile,
            learning_path,
            learning_session,
            knowledge_points,
            kp,
            use_search=use_search,
            search_rag_manager=search_rag_manager,
        )

    def draft_one_safe(kp):
        """单项草稿：捕获异常，失败返回 None（不让单点失败中断整批）。"""
        try:
            return draft_one(kp), None
        except Exception as e:  # noqa: BLE001 - 需要吞掉任意失败以隔离单点
            return None, e

    if allow_parallel:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            outcomes = list(executor.map(draft_one_safe, knowledge_points))
    else:
        outcomes = [draft_one_safe(kp) for kp in knowledge_points]

    # 逐项回填：失败项用同索引的占位草稿补位，保证返回列表与 knowledge_points 等长。
    # 下游 prepare_markdown_document 依赖"草稿下标 == 知识点下标"，绝不能丢项或错位。
    results: List[Any] = []
    failed_names: List[str] = []
    for kp, (draft, err) in zip(knowledge_points, outcomes):
        if draft is None:
            name = str(kp.get("name", "") if isinstance(kp, dict) else kp).strip() or "未命名知识点"
            failed_names.append(name)
            logger.warning(f"知识点草稿生成失败，已用占位内容补位：{name}（{type(err).__name__}: {err}）")
            results.append(_failed_draft_placeholder(kp))
        else:
            results.append(draft)
    if failed_names:
        logger.warning(f"本环节共有 {len(failed_names)}/{len(results)} 个知识点草稿生成失败：{failed_names}")
    return results


def _failed_draft_placeholder(kp) -> dict:
    """生成失败知识点的占位草稿，保持与正常草稿相同的字段结构。"""
    name = str(kp.get("name", "") if isinstance(kp, dict) else kp).strip() or "知识点"
    return {
        "title": name,
        "content": (
            f"> 本节内容生成失败（可能是网络或模型超时）。\n>\n"
            f"> 可点击页面上的「重新生成」按钮重试；本环节其他小节不受影响。"
        ),
        "generation_failed": True,
    }


if __name__ == "__main__":
    from config.loader import default_config
    from base.llm_factory import LLMFactory
    import logging

    llm = LLMFactory.from_config(default_config.llm)
    search_rag_manager = SearchRagManager.from_config(default_config)
    logging.basicConfig(level=default_config.log_level)
    logger = logging.getLogger(__name__)

    learner_profile = {"name": "Alice", "level": "intermediate"}
    learning_path = {"title": "Data Science Basics"}
    learning_session = {"title": "Introduction to Pandas"}
    knowledge_points = [
        {"name": "Pandas DataFrames"},
        {"name": "Data Cleaning with Pandas"},
    ]

    drafts = draft_knowledge_points_with_llm(
        llm,
        learner_profile,
        learning_path,
        learning_session,
        knowledge_points,
        allow_parallel=True,
        use_search=True,
    )

    for draft in drafts:
        logger.info(f"Drafted Knowledge Point: {draft}")