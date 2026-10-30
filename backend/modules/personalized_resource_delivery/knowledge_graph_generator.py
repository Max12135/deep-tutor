"""
知识图谱生成模块

生成学习进度的可视化知识图谱，包括：
- 知识节点（知识点）
- 节点关系（依赖、关联）
- 学习进度状态
"""

import json
import logging
from typing import Optional, Dict, Any, List
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class KnowledgeGraphGenerator:
    """知识图谱生成器"""

    SYSTEM_PROMPT = """You are an expert educational content designer specializing in knowledge visualization.

Your task is to create a knowledge graph structure that represents the relationships between knowledge points.

The graph should:
1. Show clear hierarchical relationships between concepts
2. Indicate prerequisite dependencies
3. Be visually appealing when rendered
4. Help learners understand the learning sequence

Output only valid JSON without any additional text or markdown formatting."""

    GRAPH_GENERATION_PROMPT = """Based on the following knowledge points, create a knowledge graph structure.

Knowledge Points:
{knowledge_points}

Learning Session Title: {session_title}
Learning Session Abstract: {session_abstract}

Create a JSON object with the following structure:
{{
    "nodes": [
        {{
            "id": "unique_id_1",
            "name": "Knowledge Point Name",
            "type": "foundational|practical|strategic",
            "description": "Brief description",
            "level": 1,
            "position_x": 0.5,
            "position_y": 0.2
        }}
    ],
    "edges": [
        {{
            "source": "source_node_id",
            "target": "target_node_id",
            "type": "prerequisite|related|extends",
            "label": "relationship description"
        }}
    ],
    "layout": {{
        "type": "linear|tree|network",
        "direction": "horizontal|vertical"
    }}
}}

Important guidelines:
1. Each node must have a unique `id` (use lowercase with underscores)
2. `position_x` and `position_y` should be values between 0 and 1, representing relative positions
3. Arrange nodes in a logical learning sequence (top-to-bottom or left-to-right)
4. For a LINEAR graph: arrange nodes in a horizontal or vertical line
5. `level` indicates the depth in the hierarchy (1 = top level)
6. Create edges to show relationships between knowledge points
7. Ensure the graph flows naturally from basic to advanced concepts

Output only the JSON object, no additional text."""


    def __init__(self, llm: BaseChatModel):
        """初始化知识图谱生成器

        Args:
            llm: LangChain LLM 实例
        """
        self.llm = llm

    def generate_graph(
        self,
        knowledge_points: List[Dict],
        session_title: str = "",
        session_abstract: str = ""
    ) -> Dict[str, Any]:
        """生成知识图谱

        Args:
            knowledge_points: 知识点列表
            session_title: 学习会话标题
            session_abstract: 学习会话摘要

        Returns:
            Dict containing:
            - nodes: 节点列表
            - edges: 边列表
            - layout: 布局配置
        """
        # 格式化知识点
        kp_text = "\n".join([
            f"- {kp.get('name', 'Unknown')} (type: {kp.get('type', 'unknown')})"
            for kp in knowledge_points
        ])

        prompt = self.GRAPH_GENERATION_PROMPT.format(
            knowledge_points=kp_text,
            session_title=session_title,
            session_abstract=session_abstract
        )

        try:
            response = self.llm.invoke([
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ])

            content = response.content

            # 提取 JSON
            graph_data = self._extract_json(content)

            if graph_data:
                # 补充默认值
                graph_data = self._ensure_graph_structure(graph_data, knowledge_points)
                return graph_data
            else:
                # 如果解析失败，生成默认图谱
                return self._create_default_graph(knowledge_points)

        except Exception as e:
            logger.error(f"Failed to generate knowledge graph: {e}")
            return self._create_default_graph(knowledge_points)

    def _extract_json(self, content: str) -> Optional[Dict]:
        """从内容中提取 JSON"""
        try:
            # 尝试直接解析
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        import re

        # 尝试匹配 ```json ... ```
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 尝试匹配 { ... }
        brace_match = re.search(r'\{[\s\S]*\}', content)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    def _ensure_graph_structure(
        self,
        graph_data: Dict,
        knowledge_points: List[Dict]
    ) -> Dict:
        """确保图谱结构完整"""
        if "nodes" not in graph_data:
            graph_data["nodes"] = []

        if "edges" not in graph_data:
            graph_data["edges"] = []

        if "layout" not in graph_data:
            graph_data["layout"] = {
                "type": "linear",
                "direction": "horizontal"
            }

        # 为每个节点添加学习状态
        for node in graph_data["nodes"]:
            if "status" not in node:
                node["status"] = "unlearned"

        return graph_data

    def _create_default_graph(self, knowledge_points: List[Dict]) -> Dict:
        """创建默认的线性知识图谱"""
        nodes = []
        edges = []

        total = len(knowledge_points)

        for i, kp in enumerate(knowledge_points):
            node_id = kp.get('name', f'node_{i}').lower().replace(' ', '_').replace('-', '_')

            # 线性布局：水平排列
            nodes.append({
                "id": node_id,
                "name": kp.get('name', f'Knowledge {i+1}'),
                "type": kp.get('type', 'foundational'),
                "description": kp.get('name', ''),
                "level": 1,
                "position_x": (i + 1) / (total + 1) if total > 0 else 0.5,
                "position_y": 0.5,
                "status": "unlearned"
            })

            # 创建与前一个节点的连接
            if i > 0:
                prev_node_id = nodes[i-1]["id"]
                edges.append({
                    "source": prev_node_id,
                    "target": node_id,
                    "type": "sequence",
                    "label": "next"
                })

        return {
            "nodes": nodes,
            "edges": edges,
            "layout": {
                "type": "linear",
                "direction": "horizontal"
            }
        }


def generate_knowledge_graph_with_llm(
    llm: BaseChatModel,
    knowledge_points: List[Dict],
    session_title: str = "",
    session_abstract: str = ""
) -> Dict[str, Any]:
    """生成知识图谱的便捷函数

    Args:
        llm: LangChain LLM 实例
        knowledge_points: 知识点列表
        session_title: 学习会话标题
        session_abstract: 学习会话摘要

    Returns:
        Dict containing graph data
    """
    generator = KnowledgeGraphGenerator(llm)
    return generator.generate_graph(knowledge_points, session_title, session_abstract)


def update_graph_progress(
    graph_data: Dict[str, Any],
    node_id: str,
    status: str = "completed"
) -> Dict[str, Any]:
    """更新知识图谱中节点的学习状态

    Args:
        graph_data: 图谱数据
        node_id: 节点ID
        status: 新状态 (unlearned, in_progress, completed)

    Returns:
        更新后的图谱数据
    """
    for node in graph_data.get("nodes", []):
        if node.get("id") == node_id:
            node["status"] = status
            break

    return graph_data
