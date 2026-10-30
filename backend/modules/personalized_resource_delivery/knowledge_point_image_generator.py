"""
知识点图片生成器

为每个知识点生成相关的可视化图片，例如：
- 学习"具身机器人"时，生成机器人的图片
- 学习"数学公式"时，生成公式可视化图
- 学习"编程概念"时，生成代码流程图
"""

import json
import re
import time
import logging
from typing import Optional, Dict, Any, List
from langchain_core.language_models import BaseChatModel

from utils.parsers import safe_parse

logger = logging.getLogger(__name__)

# 豆包(Seedream)熔断策略：连续失败达到阈值才进入冷却，冷却结束后自动恢复尝试。
# 早期实现是"一次失败即永久禁用"（重启后端才恢复），瞬时网络抖动也会把豆包废掉，
# 故改为"失败计数 + 时间窗"，兼顾不重复打失败请求与能自动恢复。
_DOUBAO_FAILURE_THRESHOLD = 2      # 连续失败次数阈值
_DOUBAO_COOLDOWN_SECONDS = 300     # 熔断冷却时长（秒）
_DOUBAO_FAILURE_COUNT = 0          # 连续失败计数（成功即清零）
_DOUBAO_DISABLED_UNTIL = 0.0       # 冷却截止时间戳；0 表示未熔断
_DOUBAO_DISABLED_REASON: Optional[str] = None


def _doubao_is_disabled() -> bool:
    """当前是否处于豆包熔断冷却期（冷却结束后自动恢复尝试）。"""
    return time.time() < _DOUBAO_DISABLED_UNTIL


def _reset_doubao_breaker() -> None:
    """豆包调用成功时复位熔断状态。"""
    global _DOUBAO_FAILURE_COUNT, _DOUBAO_DISABLED_UNTIL, _DOUBAO_DISABLED_REASON
    _DOUBAO_FAILURE_COUNT = 0
    _DOUBAO_DISABLED_UNTIL = 0.0
    _DOUBAO_DISABLED_REASON = None


def _record_doubao_failure(reason: Optional[str]) -> None:
    """记录一次豆包失败；达到阈值则进入冷却窗口（而非永久禁用）。"""
    global _DOUBAO_FAILURE_COUNT, _DOUBAO_DISABLED_UNTIL, _DOUBAO_DISABLED_REASON
    _DOUBAO_FAILURE_COUNT += 1
    if reason:
        _DOUBAO_DISABLED_REASON = reason
    if _DOUBAO_FAILURE_COUNT >= _DOUBAO_FAILURE_THRESHOLD:
        _DOUBAO_DISABLED_UNTIL = time.time() + _DOUBAO_COOLDOWN_SECONDS
        logger.warning(
            "豆包生图连续失败 %d 次，进入 %d 秒冷却后自动重试。原因：%s",
            _DOUBAO_FAILURE_COUNT, _DOUBAO_COOLDOWN_SECONDS, _DOUBAO_DISABLED_REASON,
        )


def get_doubao_fallback_notice() -> Optional[str]:
    """处于熔断冷却期时返回用户可读提示；否则返回 None。"""
    return _DOUBAO_DISABLED_REASON if _doubao_is_disabled() else None


class KnowledgePointImageGenerator:
    """知识点图片生成器"""

    # 不同类型知识点的图片生成提示词
    PROMPT_TEMPLATES = {
        "foundational": {
            "description": "基础概念图",
            "prompt_template": """Create an educational illustration for the knowledge point: {knowledge_point}

            Context: {session_title}

            The illustration should:
            - Visually represent the core concept
            - Be simple and clear for beginners
            - Use educational style with clear labels
            - Include visual elements that help understanding
            - Show the concept in a practical, relatable way

            Style: {style}
            Make it suitable for educational materials and presentations.
            """,
        },
        "practical": {
            "description": "实际应用图",
            "prompt_template": """Create a practical application illustration for: {knowledge_point}

            Context: {session_title}

            The illustration should:
            - Show real-world application or use case
            - Include people or objects demonstrating the concept
            - Be realistic and informative
            - Show how this knowledge point is applied
            - Include labels for key components

            Style: {style}
            Make it realistic enough to show actual application but stylized for clarity.
            """,
        },
        "strategic": {
            "description": "战略思维图",
            "prompt_template": """Create a strategic thinking diagram for: {knowledge_point}

            Context: {session_title}

            The illustration should:
            - Show high-level concepts and relationships
            - Include decision-making elements
            - Show how this knowledge point fits into the bigger picture
            - Include flow or process visualization
            - Use abstract but clear visual representation

            Style: {style}
            Make it suitable for understanding strategic concepts at a glance.
            """,
        },
    }

    # 可视化风格
    VISUAL_STYLES = {
        "educational": "Clean, modern educational illustration with clear labels",
        "realistic": "Realistic photography-style illustration",
        "diagrammatic": "Clear diagram with lines, boxes, and annotations",
        "infographic": "Modern infographic style with icons and data visualization",
        "minimalist": "Simple minimalist line art with limited colors",
        "colorful": "Vibrant, colorful illustration that appeals to learners",
    }

    def __init__(self, llm: BaseChatModel):
        """初始化知识点图片生成器

        Args:
            llm: LangChain LLM 实例
        """
        self.llm = llm

    def generate_image_for_knowledge_point(
        self,
        knowledge_point: Dict[str, Any],
        session_title: str,
        session_abstract: str = "",
        knowledge_description: str = "",
        visual_style: str = "educational",
        size: str = "1024x1024",
        prompt_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """为单个知识点生成图片

        Args:
            knowledge_point: 知识点数据
                {
                    "name": "知识点名称",
                    "type": "foundational|practical|strategic",
                    "description": "知识点描述"
                }
            session_title: 学习会话标题
            session_abstract: 学习会话摘要
            knowledge_description: 详细的知识描述（可选）
            visual_style: 可视化风格
            size: 图像尺寸
            prompt_override: 若提供，则直接把它当作完整生图提示词（跳过模板拼装）

        Returns:
            Dict containing:
            - image_url: 生成的图像 URL
            - prompt: 使用的提示词
            - knowledge_point_id: 知识点 ID
            - visual_style: 使用的视觉风格
            - success: 是否成功
        """
        kp_name = knowledge_point.get("name", "Unknown Knowledge Point")
        kp_type = knowledge_point.get("type", "foundational")
        kp_desc = knowledge_point.get("description", kp_name)

        # 获取对应类型的提示词模板
        template_info = self.PROMPT_TEMPLATES.get(
            kp_type,
            self.PROMPT_TEMPLATES["foundational"]
        )

        # 获取视觉风格描述
        style_desc = self.VISUAL_STYLES.get(
            visual_style,
            self.VISUAL_STYLES["educational"]
        )

        # 构建完整的提示词
        prompt = template_info["prompt_template"].format(
            knowledge_point=kp_name,
            session_title=session_title,
            style=style_desc
        )

        # 如果有额外的知识描述，添加到提示词中
        if knowledge_description:
            prompt += f"\n\nAdditional Context:\n{knowledge_description}"

        if session_abstract:
            prompt += f"\n\nSession Overview: {session_abstract}"

        # 规划阶段已经写好具体生图 brief 时，直接用 brief 作为生图提示词
        if prompt_override:
            prompt = prompt_override

        try:
            from .image_generator import generate_learning_image_with_llm

            result = None
            # 优先用豆包(Seedream)按知识点内容生成插图，图与内容强相关
            if not _doubao_is_disabled():
                result = generate_learning_image_with_llm(
                    llm=self.llm,
                    learning_content=prompt,   # 这里已是完整插图提示词
                    image_type="summary_poster",
                    style=visual_style,
                    size=size,
                    use_llm_enhancement=False,
                    image_mode="doubao",
                    prompt_is_ready=True,
                )
                if result and result.get("image_url"):
                    # 成功即复位熔断，避免历史失败一直压着
                    _reset_doubao_breaker()
                else:
                    # 豆包不可用（Key 无效/欠费/模型未开通/额度不足/网络异常）→ 本次回退必应；
                    # 连续失败达阈值后进入冷却，冷却结束会自动再试
                    reason = result.get("error_message") if isinstance(result, dict) else None
                    _record_doubao_failure(reason or "豆包生图不可用，配图已回退为必应图片搜索。")

            # 回退：必应图片搜索；直接用知识点名称作查询词，比泛化英文关键词相关得多
            if not (result and result.get("image_url")):
                result = generate_learning_image_with_llm(
                    llm=self.llm,
                    learning_content=prompt,
                    image_type="summary_poster",
                    style=visual_style,
                    size=size,
                    use_llm_enhancement=False,
                    image_mode="search",
                    search_query=kp_name,
                )

            if result:
                result["knowledge_point_id"] = self._get_kp_id(knowledge_point)
                result["knowledge_point_name"] = kp_name
                result["visual_style"] = visual_style
                _doubao_notice = get_doubao_fallback_notice()
                if _doubao_notice:
                    # 本次实际走的是必应回退（豆包处于冷却期），把原因带上供前端提示
                    result["doubao_fallback_notice"] = _doubao_notice

            return result

        except Exception as e:
            logger.error(f"Failed to generate image for knowledge point '{kp_name}': {e}", exc_info=True)
            return {
                "image_url": None,
                "prompt": prompt,
                "knowledge_point_id": self._get_kp_id(knowledge_point),
                "knowledge_point_name": kp_name,
                "visual_style": visual_style,
                "success": False,
                "error": str(e)
            }

    def _get_kp_id(self, knowledge_point: Dict[str, Any]) -> str:
        """生成知识点 ID"""
        name = knowledge_point.get("name", "unknown")
        return name.lower().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "")

    @staticmethod
    def _parse_plan(text: str) -> Optional[List[Dict[str, str]]]:
        """解析 LLM 输出的配图规划 JSON，失败返回 None。"""
        if not text or not isinstance(text, str):
            return None

        cleaned = text.strip()
        # 去掉 ```json ... ``` 代码块围栏
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        data = safe_parse(cleaned)
        if not isinstance(data, dict):
            # 兜底：截取第一个 { 到最后一个 } 之间的内容再解析
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start != -1 and end > start:
                data = safe_parse(cleaned[start:end + 1])
        if not isinstance(data, dict):
            return None

        selections = data.get("selections")
        if not isinstance(selections, list):
            return None

        result: List[Dict[str, str]] = []
        for sel in selections:
            if isinstance(sel, dict) and sel.get("name"):
                result.append({
                    "name": str(sel["name"]).strip(),
                    "brief": str(sel.get("brief", "")).strip(),
                })
        return result

    def _plan_images(
        self,
        knowledge_points: List[Dict[str, Any]],
        session_title: str,
        session_abstract: str = "",
        max_images: int = 5
    ) -> Optional[List[Dict[str, str]]]:
        """让 LLM 判断哪些知识点值得配图，并为选中的点写出具体生图 brief。

        Returns:
            - list（可能为空）: 规划成功，只对其中选中的知识点生图
            - None: 规划失败（LLM 报错 / 输出无法解析），调用方应回退到默认策略
        """
        if not knowledge_points:
            return []

        lines = []
        for i, kp in enumerate(knowledge_points, 1):
            name = kp.get("name", f"Knowledge Point {i}")
            desc = kp.get("description", "") or name
            kp_type = kp.get("type", "foundational")
            lines.append(f"[{i}] name: {name}\n    description: {desc}\n    type: {kp_type}")
        candidates = "\n".join(lines)

        prompt = f"""You are an instructional designer deciding which knowledge points in a learning session genuinely benefit from an illustration.

Session Title: {session_title}
Session Overview: {session_abstract or "(none)"}

Candidate Knowledge Points:
{candidates}

Task:
- Select ONLY the knowledge points where a single illustration would meaningfully aid understanding (e.g. a concrete object, a process/flow, a structure, a spatial or visual concept, a step-by-step procedure).
- Do NOT illustrate abstract or purely verbal points that have no visual anchor (e.g. "the importance of X", "best practices", or a plain definition).
- It is completely fine to select nothing (0), just 1, or 2 points. Do NOT force one image per knowledge point.
- Select at most {max_images} points, in priority order.
- For each selected point, write a concrete English image brief describing the subject, the key elements, any labels/text to display, and the layout. Make it specific enough that the illustration is clearly about that exact knowledge point.

Return ONLY a JSON object, no markdown, no explanation:
{{"selections": [{{"name": "<exact knowledge point name as listed above>", "brief": "<concrete English image brief>"}}]}}
"""

        try:
            response = self.llm.invoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.warning(f"生图规划调用 LLM 失败，将回退到默认策略: {e}")
            return None

        plan = self._parse_plan(text)
        if plan is None:
            logger.warning("生图规划输出无法解析，将回退到默认策略。")
        return plan

    def _resolve_knowledge_point(
        self,
        name: str,
        knowledge_points: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """把规划里返回的知识点名称映射回原知识点对象（精确→忽略大小写→子串）。"""
        if not name:
            return None
        for kp in knowledge_points:
            if kp.get("name", "") == name:
                return kp
        lowered = name.lower()
        for kp in knowledge_points:
            if str(kp.get("name", "")).lower() == lowered:
                return kp
        for kp in knowledge_points:
            cname = str(kp.get("name", ""))
            if cname and (cname in name or name in cname):
                return kp
        return None

    def generate_images_for_session(
        self,
        knowledge_points: List[Dict[str, Any]],
        session_title: str,
        session_abstract: str = "",
        visual_style: str = "educational",
        size: str = "1024x1024",
        max_images: int = 5
    ) -> List[Dict[str, Any]]:
        """为学习会话生成图片

        先生成"生图思路"：让 LLM 判断哪些知识点值得配图（可能一个都不配），
        并只为选中的知识点生成图片，避免"每个知识点硬塞一张不相关的图"。

        Args:
            knowledge_points: 知识点列表
            session_title: 学习会话标题
            session_abstract: 学习会话摘要
            visual_style: 可视化风格
            size: 图像尺寸
            max_images: 最多生成多少张图片

        Returns:
            List of image generation results（可能为空列表）
        """
        if not knowledge_points:
            return []

        plan = self._plan_images(
            knowledge_points, session_title, session_abstract, max_images
        )

        # 把规划结果整理成待生成列表 [(knowledge_point, brief 或 None)]
        selected: List[Dict[str, Any]] = []
        if plan is None:
            # 规划失败：回退到默认策略（按顺序取前 max_images 个，沿用模板提示词）
            logger.info(f"生图规划不可用，回退为默认策略：为前 {max_images} 个知识点配图。")
            for kp in knowledge_points[:max_images]:
                selected.append({"knowledge_point": kp, "brief": None})
        else:
            for sel in plan:
                kp = self._resolve_knowledge_point(sel["name"], knowledge_points)
                if kp is not None:
                    selected.append({"knowledge_point": kp, "brief": sel.get("brief") or None})

            if not selected:
                logger.info(f"LLM 判断本会话无需配图（共 {len(knowledge_points)} 个知识点均不适合可视化）。")
                return []

        results = []
        for i, item in enumerate(selected):
            kp = item["knowledge_point"]
            logger.info(f"Generating image {i+1}/{len(selected)} for knowledge point: {kp.get('name', 'Unknown')}")

            result = self.generate_image_for_knowledge_point(
                knowledge_point=kp,
                session_title=session_title,
                session_abstract=session_abstract,
                visual_style=visual_style,
                size=size,
                prompt_override=item["brief"]
            )

            results.append(result)

        return results


def generate_knowledge_point_image_with_llm(
    llm: BaseChatModel,
    knowledge_point: Dict[str, Any],
    session_title: str,
    session_abstract: str = "",
    knowledge_description: str = "",
    visual_style: str = "educational",
    size: str = "1024x1024"
) -> Dict[str, Any]:
    """为知识点生成图片的便捷函数

    Args:
        llm: LangChain LLM 实例
        knowledge_point: 知识点数据
        session_title: 学习会话标题
        session_abstract: 学习会话摘要
        knowledge_description: 详细的知识描述
        visual_style: 可视化风格
        size: 图像尺寸

    Returns:
        Dict containing image generation result
    """
    generator = KnowledgePointImageGenerator(llm)
    return generator.generate_image_for_knowledge_point(
        knowledge_point=knowledge_point,
        session_title=session_title,
        session_abstract=session_abstract,
        knowledge_description=knowledge_description,
        visual_style=visual_style,
        size=size
    )


def generate_session_images_with_llm(
    llm: BaseChatModel,
    knowledge_points: List[Dict[str, Any]],
    session_title: str,
    session_abstract: str = "",
    visual_style: str = "educational",
    size: str = "1024x1024",
    max_images: int = 5
) -> List[Dict[str, Any]]:
    """为学习会话生成所有知识点图片的便捷函数

    Args:
        llm: LangChain LLM 实例
        knowledge_points: 知识点列表
        session_title: 学习会话标题
        session_abstract: 学习会话摘要
        visual_style: 可视化风格
        size: 图像尺寸
        max_images: 最多生成多少张图片

    Returns:
        List of image generation results
    """
    generator = KnowledgePointImageGenerator(llm)
    return generator.generate_images_for_session(
        knowledge_points=knowledge_points,
        session_title=session_title,
        session_abstract=session_abstract,
        visual_style=visual_style,
        size=size,
        max_images=max_images
    )
