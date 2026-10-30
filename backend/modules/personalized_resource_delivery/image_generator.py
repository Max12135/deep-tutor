"""
多模态内容生成模块 - 图像生成器

支持三种图像获取方式:
1. 网络搜索图片（关键词 → 微软必应图片搜索）
2. OpenAI DALL-E 生成（可选，需要 API Key）
3. 豆包/火山引擎 Seedream 生成（可选，需要 API Key）

图片搜索：微软必应图片（cn.bing.com，国内可直接访问，无需 API Key）
"""

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# 图库/壁纸/素材站：必应图片搜索"概念类"查询时的高频无关来源，优先跳过
_JUNK_IMAGE_HOSTS = (
    "699pic", "netbian", "bobopic", "zcool", "duitang", "nipic", "veer",
    "58pic", "16pic", "ivsky", "hiwallpaper", "wallpaper", "tupian",
    "pexels", "unsplash", "shutterstock", "gettyimages",
)

# 豆包(Seedream)默认模型 id：需在火山方舟控制台「开通管理」里激活该模型后才能调用。
# 账号可用的模型列表：GET https://ark.cn-beijing.volces.com/api/v3/models
_DEFAULT_DOUBAO_IMAGE_MODEL = "doubao-seedream-5-0-flash-260915"


# ---------------------------------------------------------------------------
# 网络图片搜索（微软必应图片搜索，国内可直接访问）
# ---------------------------------------------------------------------------

def _search_image_bing(keyword: str, max_results: int = 5) -> Optional[str]:
    """
    使用微软必应图片搜索（通过 HTML 页面解析），返回第一个可用的图片 URL。

    Args:
        keyword: 搜索关键词
        max_results: 最多尝试多少个结果

    Returns:
        图片 URL 字符串，搜索失败则返回 None
    """
    import html  # 延迟导入，避免顶层导入问题
    
    try:
        encoded = urllib.parse.quote(keyword)
        # 微软中国必应图片搜索
        url = f"https://cn.bing.com/images/search?q={encoded}&first=0&count={max_results * 2}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
        
        # 从 HTML 中提取 murl 字段
        pattern = r'&quot;murl&quot;:&quot;(https?://[^&]+)&quot;'
        matches = re.findall(pattern, content)
        
        # 解码 HTML 实体
        urls = [html.unescape(m) for m in matches]
        
        # 过滤有效的图片 URL
        valid_urls = [
            u for u in urls 
            if u.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))
        ]
        
        if valid_urls:
            # 优先跳过图库/壁纸站（图文无关的重灾区），若全被过滤则退回首张
            good_urls = [u for u in valid_urls if not any(h in u.lower() for h in _JUNK_IMAGE_HOSTS)]
            result_url = (good_urls or valid_urls)[0]
            logger.info(f"必应图片搜索成功: {keyword} -> {result_url[:60]}...")
            return result_url
            
        logger.warning(f"必应图片搜索无结果: {keyword}")
        return None
    except Exception as e:
        logger.warning(f"必应图片搜索失败: {e}")
        return None


# ---------------------------------------------------------------------------
# 网络图片搜索（DuckDuckGo，已弃用）
# ---------------------------------------------------------------------------

def _search_image_duckduckgo(keyword: str, max_results: int = 5) -> Optional[str]:
    """
    使用 DuckDuckGo 图片搜索，返回第一个可用的图片 URL。

    Args:
        keyword: 搜索关键词
        max_results: 最多尝试多少个结果

    Returns:
        图片 URL 字符串，搜索失败则返回 None
    """
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(keyword, max_results=max_results))
        for r in results:
            url = r.get("image") or r.get("url")
            if url and url.startswith("http"):
                return url
        return None
    except ImportError:
        logger.warning("duckduckgo_search not installed, falling back to HTTP search")
        return _search_image_duckduckgo_http(keyword)
    except Exception as e:
        logger.warning(f"DuckDuckGo search failed: {e}")
        return _search_image_duckduckgo_http(keyword)


def _search_image_duckduckgo_http(keyword: str) -> Optional[str]:
    """
    通过 DuckDuckGo HTTP API 搜索图片（备用方案，无需第三方库）。
    """
    try:
        encoded = urllib.parse.quote(keyword)
        # DuckDuckGo iZone API（返回 JSON）
        url = f"https://duckduckgo.com/?q={encoded}&iax=images&ia=images&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("results", [])
        for r in results:
            img_url = r.get("image")
            if img_url and img_url.startswith("http"):
                return img_url
        return None
    except Exception as e:
        logger.warning(f"HTTP DuckDuckGo image search failed: {e}")
        return None


def _build_search_keywords(
    learning_content: str,
    image_type: str,
    llm=None
) -> str:
    """
    根据学习内容和图像类型，构建最优搜索关键词。
    如果有 LLM 则请 LLM 生成，否则基于规则生成。
    """
    if llm is not None:
        try:
            prompt = f"""Based on the following learning content, generate 3-5 concise English search keywords
for finding an educational image of type '{image_type}'.

Learning Content:
{learning_content[:500]}

Output ONLY the keywords separated by spaces, no explanation."""
            response = llm.invoke(prompt)
            keywords = response.content.strip()
            # 清理多余字符
            keywords = re.sub(r'[^\w\s\-]', ' ', keywords).strip()
            if keywords:
                return keywords
        except Exception as e:
            logger.warning(f"LLM keyword generation failed: {e}")

    # 规则兜底：截取前80字符 + 类型词
    type_suffix = {
        "mind_map": "mind map diagram",
        "knowledge_tree": "knowledge tree education",
        "concept_diagram": "concept diagram education",
        "summary_poster": "educational summary infographic",
        "learning_roadmap": "learning roadmap education",
    }.get(image_type, "educational diagram")

    # 从 learning_content 提取第一行作为主题
    first_line = learning_content.split("\n")[0][:80].strip()
    return f"{first_line} {type_suffix}"


# ---------------------------------------------------------------------------
# 图像生成器主类
# ---------------------------------------------------------------------------

def _classify_doubao_error(e: Exception) -> tuple[str, str]:
    """把豆包(火山方舟)生图异常翻译成 (错误码, 用户可读中文说明)。"""
    text = str(e)
    low = text.lower()
    if "overdue" in low or "accountoverdue" in low or "欠费" in text:
        return (
            "doubao_account_overdue",
            "豆包账户已欠费或余额不足，请到火山方舟控制台充值；本次配图已回退为必应图片搜索。",
        )
    if "modelnotopen" in low or "model not open" in low or "not activated" in low:
        return (
            "doubao_model_not_open",
            "所用豆包图像模型尚未开通，请在火山方舟控制台「开通管理」中激活该模型；本次配图已回退为必应图片搜索。",
        )
    if "setlimitexceeded" in low or "rate limit" in low or "429" in low or "quota" in low or "exceed" in low:
        return (
            "doubao_quota",
            "豆包调用额度或频率受限（已达上限），请稍后重试或在控制台提额；本次配图已回退为必应图片搜索。",
        )
    if "401" in low or "authentication" in low or "api key" in low or "unauthorized" in low:
        return (
            "doubao_auth",
            "豆包 API Key 无效或未正确配置（VOLCENGINE_API_KEY），请检查后重试；本次配图已回退为必应图片搜索。",
        )
    return (
        "doubao_error",
        f"豆包生图失败（{type(e).__name__}）；本次配图已回退为必应图片搜索。",
    )


class LearningImageGenerator:
    """学习内容图像生成器（支持搜索模式 & DALL-E 模式）"""

    # 图像类型对应的提示词模板（用于 DALL-E 生成模式）
    IMAGE_TYPE_PROMPTS = {
        "knowledge_tree": {
            "description": "知识树/知识结构图",
            "prompt_template": """Create an educational knowledge tree diagram for learning {topic}.
            The diagram should show:
            - Main topic at the root
            - Key concepts as branches
            - Sub-concepts as leaves
            - Connections between related concepts

            Style: {style}
            Use clear labels and a structured layout suitable for learning."""
        },
        "mind_map": {
            "description": "思维导图",
            "prompt_template": """Create an educational mind map for learning {topic}.
            The mind map should show:
            - Central topic in the middle
            - Main branches radiating from center
            - Related subtopics connected to main branches
            - Visual hierarchy showing relationships

            Style: {style}
            Use colors, icons, and clear organization for effective learning."""
        },
        "concept_diagram": {
            "description": "概念图/关系图",
            "prompt_template": """Create an educational concept diagram explaining {topic}.
            The diagram should:
            - Show key concepts and their relationships
            - Use arrows to indicate cause-effect, dependencies, or hierarchies
            - Include brief labels explaining connections
            - Present information in a clear, organized way

            Style: {style}
            Make it visually appealing and easy to understand for students."""
        },
        "summary_poster": {
            "description": "学习总结海报",
            "prompt_template": """Create an educational summary poster for {topic}.
            The poster should:
            - Summarize key points of the topic
            - Use visual elements like icons, diagrams, and bullet points
            - Be visually engaging and memorable
            - Include important formulas, definitions, or key takeaways

            Style: {style}
            Make it colorful, informative, and suitable for study purposes."""
        },
        "learning_roadmap": {
            "description": "学习路线图",
            "prompt_template": """Create an educational learning roadmap for mastering {topic}.
            The roadmap should:
            - Show sequential learning steps from basics to advanced
            - Indicate prerequisites and dependencies
            - Mark key milestones and achievements
            - Show estimated difficulty progression

            Style: {style}
            Make it clear, motivating, and suitable for self-study planning."""
        }
    }

    # 风格描述
    STYLE_DESCRIPTIONS = {
        "educational": "Clean, professional educational style with clear diagrams and readable text",
        "cartoon": "Friendly cartoon style with colorful illustrations, suitable for visual learners",
        "minimalist": "Minimalist modern design with clean lines and limited color palette",
        "detailed": "Detailed and comprehensive illustration with rich visual information",
        "infographic": "Modern infographic style with data visualization elements",
        "sketch": "Hand-drawn sketch style, casual and approachable"
    }

    def __init__(
        self,
        image_mode: str = "search",       # "search" | "dalle" | "doubao"
        llm_provider: str = "openai",
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ):
        """
        初始化图像生成器

        Args:
            image_mode: 图像获取方式
                - "search": 从网络搜索图片（默认，无需 API Key）
                - "dalle": 使用 OpenAI DALL-E 生成
                - "doubao": 使用豆包/火山引擎 Seedream 生成
            llm_provider: 图像生成服务提供商（仅 dalle/doubao 模式使用）
            model_name: 模型名称（仅 dalle/doubao 模式使用）
            api_key: API 密钥（仅 dalle/doubao 模式使用）
            base_url: 自定义 API 端点（仅 dalle/doubao 模式使用）
        """
        self.image_mode = image_mode
        self.llm_provider = llm_provider
        self.model_name = model_name
        # 优先使用传入的 api_key，其次检查环境变量
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("VOLCENGINE_API_KEY")
        self.base_url = base_url or os.getenv("DOUBAO_IMAGE_BASE_URL")
        
        # 豆包 API 默认配置
        if image_mode == "doubao":
            if not self.base_url:
                self.base_url = "https://ark.cn-beijing.volces.com/api/v3"
            # 关键：豆包模式绝不能沿用 dalle 的默认模型，否则会把 dall-e-3 发给火山引擎导致失败
            if not self.model_name or self.model_name == "dall-e-3":
                self.model_name = os.getenv("DOUBAO_IMAGE_MODEL", _DEFAULT_DOUBAO_IMAGE_MODEL)
        elif image_mode == "dalle" and not self.model_name:
            self.model_name = "dall-e-3"

    def generate_image(
        self,
        learning_content: str,
        image_type: str = "mind_map",
        style: str = "educational",
        size: str = "1024x1024",
        quality: str = "standard",
        llm=None,
        search_query: Optional[str] = None,
        prompt_is_ready: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成学习相关图像

        Args:
            learning_content: 学习内容描述
            image_type: 图像类型
            style: 视觉风格
            size: 图像尺寸（仅 DALL-E/豆包 模式有效）
            quality: 图像质量（仅 DALL-E 模式有效）
            llm: LangChain LLM 实例（搜索模式用于生成关键词，可为 None）

        Returns:
            Dict containing:
            - image_url: 图片 URL
            - prompt / keywords: 使用的提示词或关键词
            - image_type: 图像类型
            - source: "search" | "dalle" | "doubao"
            - success: 是否成功
        """
        if self.image_mode == "search":
            return self._generate_with_search(learning_content, image_type, llm, search_query=search_query)
        elif self.image_mode == "doubao":
            return self._generate_with_doubao(learning_content, image_type, style, size, prompt_is_ready=prompt_is_ready)
        else:
            return self._generate_with_dalle(learning_content, image_type, style, size, quality)

    # ------------------------------------------------------------------
    # 搜索模式
    # ------------------------------------------------------------------

    def _generate_with_search(
        self,
        learning_content: str,
        image_type: str,
        llm=None,
        search_query: Optional[str] = None
    ) -> Dict[str, Any]:
        """通过关键词搜索获取图片"""
        # search_query 优先：调用方已确定精准查询词（如知识点名称）时直接用，避免被泛化
        keywords = search_query or _build_search_keywords(learning_content, image_type, llm)
        logger.info(f"Searching image with keywords: {keywords}")

        # 使用微软必应图片搜索（国内可直接访问）
        image_url = _search_image_bing(keywords)

        if image_url:
            return {
                "image_url": image_url,
                "keywords": keywords,
                "image_type": image_type,
                "source": "bing",
                "success": True
            }

        # 关键词简化后再试一次
        short_keywords = " ".join(keywords.split()[:3])
        logger.info(f"简化关键词重试: {short_keywords}")
        image_url = _search_image_bing(short_keywords)
        if image_url:
            return {
                "image_url": image_url,
                "keywords": short_keywords,
                "image_type": image_type,
                "source": "bing",
                "success": True
            }
            
        logger.warning(f"所有图片搜索方式均失败，关键词: {keywords}")
        return {
            "image_url": None,
            "keywords": keywords,
            "image_type": image_type,
            "source": "bing",
            "success": False,
            "detail": "No image found for the given keywords"
        }

    # ------------------------------------------------------------------
    # DALL-E 生成模式
    # ------------------------------------------------------------------

    def _generate_with_dalle(
        self,
        learning_content: str,
        image_type: str,
        style: str,
        size: str,
        quality: str
    ) -> Dict[str, Any]:
        """使用 OpenAI DALL-E 生成图像"""
        prompt = self._build_prompt(learning_content, image_type, style)
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            response = client.images.generate(
                model=self.model_name or "dall-e-3",
                prompt=prompt,
                size=size,
                quality=quality,
                n=1
            )
            image_url = response.data[0].url
            revised_prompt = getattr(response.data[0], "revised_prompt", prompt)
            client.close()
            return {
                "image_url": image_url,
                "prompt": revised_prompt,
                "image_type": image_type,
                "source": "dalle",
                "success": True
            }
        except Exception as e:
            logger.error(f"DALL-E image generation failed: {e}", exc_info=True)
            return {
                "image_url": None,
                "prompt": prompt,
                "image_type": image_type,
                "source": "dalle",
                "success": False,
                "detail": str(e)
            }

    # ------------------------------------------------------------------
    # 豆包/火山引擎 Seedream 生成模式
    # ------------------------------------------------------------------

    def _generate_with_doubao(
        self,
        learning_content: str,
        image_type: str,
        style: str,
        size: str = "1024x1024",
        prompt_is_ready: bool = False
    ) -> Dict[str, Any]:
        """使用豆包/火山引擎 Seedream 生成图像"""
        # prompt_is_ready=True 时 learning_content 已是完整提示词，不再套模板
        prompt = learning_content if prompt_is_ready else self._build_prompt(learning_content, image_type, style)
        
        if not self.api_key:
            return {
                "image_url": None,
                "prompt": prompt,
                "image_type": image_type,
                "source": "doubao",
                "success": False,
                "detail": "VOLCENGINE_API_KEY 环境变量未设置，请配置豆包 API Key",
                "error_code": "doubao_no_key",
                "error_message": "未配置 VOLCENGINE_API_KEY，配图已回退为必应图片搜索。",
            }
        
        try:
            from openai import OpenAI
            
            # 豆包 API 使用 OpenAI 兼容格式
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url or "https://ark.cn-beijing.volces.com/api/v3"
            )
            
            # Ark 图像接口：确保返回 URL；学习配图不加水印；尺寸改用 1K/2K/4K 简写
            size_map = {"1024x1024": "1K", "2048x2048": "2K", "4096x4096": "4K"}
            ark_size = size_map.get((size or "").lower(), size or "1K")
            response = client.images.generate(
                model=self.model_name or _DEFAULT_DOUBAO_IMAGE_MODEL,
                prompt=prompt,
                size=ark_size,
                response_format="url",
                extra_body={"watermark": False},
                n=1
            )
            
            image_url = response.data[0].url
            revised_prompt = getattr(response.data[0], "revised_prompt", prompt)
            client.close()
            
            logger.info(f"豆包图像生成成功: {image_url[:60]}...")
            return {
                "image_url": image_url,
                "prompt": revised_prompt,
                "image_type": image_type,
                "source": "doubao",
                "success": True
            }
        except Exception as e:
            error_code, error_message = _classify_doubao_error(e)
            logger.error(f"豆包图像生成失败[{error_code}]: {e}", exc_info=True)
            return {
                "image_url": None,
                "prompt": prompt,
                "image_type": image_type,
                "source": "doubao",
                "success": False,
                "detail": str(e),
                "error_code": error_code,
                "error_message": error_message,
            }

    def _build_prompt(
        self,
        learning_content: str,
        image_type: str,
        style: str
    ) -> str:
        """构建图像生成提示词（DALL-E 模式）"""
        template_info = self.IMAGE_TYPE_PROMPTS.get(
            image_type,
            self.IMAGE_TYPE_PROMPTS["mind_map"]
        )
        style_desc = self.STYLE_DESCRIPTIONS.get(style, self.STYLE_DESCRIPTIONS["educational"])
        return template_info["prompt_template"].format(
            topic=learning_content,
            style=style_desc
        )

    # ------------------------------------------------------------------
    # LLM 增强描述后生成（兼容旧接口）
    # ------------------------------------------------------------------

    def generate_with_llm_description(
        self,
        llm,
        learning_content: str,
        learning_path: Optional[Dict] = None,
        knowledge_points: Optional[str] = None,
        image_type: str = "mind_map",
        style: str = "educational",
        size: str = "1024x1024"
    ) -> Dict[str, Any]:
        """
        使用 LLM 增强描述后生成图像。
        - 搜索模式：LLM 用于生成更精准的搜索关键词
        - DALL-E 模式：LLM 用于丰富图像描述提示词
        """
        if self.image_mode == "search":
            # 搜索模式：LLM 生成关键词
            enhancement_prompt = self._build_enhancement_prompt(
                learning_content, learning_path, knowledge_points, image_type
            )
            try:
                enhanced_description = llm.invoke(enhancement_prompt).content
            except Exception:
                enhanced_description = learning_content
            return self._generate_with_search(enhanced_description, image_type, llm)
        else:
            # DALL-E 模式：LLM 丰富描述
            enhancement_prompt = self._build_enhancement_prompt(
                learning_content, learning_path, knowledge_points, image_type
            )
            try:
                enhanced_description = llm.invoke(enhancement_prompt).content
            except Exception:
                enhanced_description = learning_content
            return self.generate_image(
                learning_content=enhanced_description,
                image_type=image_type,
                style=style,
                size=size
            )

    def _build_enhancement_prompt(
        self,
        learning_content: str,
        learning_path: Optional[Dict],
        knowledge_points: Optional[str],
        image_type: str
    ) -> str:
        """构建描述增强提示词"""
        prompt_parts = [
            f"""You are an expert educational content designer. Analyze the following learning content
and create a detailed, specific description for generating an educational {image_type} image.

Learning Content: {learning_content}
"""
        ]
        if learning_path:
            prompt_parts.append(f"\nLearning Path: {json.dumps(learning_path, ensure_ascii=False)}")
        if knowledge_points:
            prompt_parts.append(f"\nKey Knowledge Points: {knowledge_points}")
        prompt_parts.append("""
Your task is to create a detailed image description that:
1. Captures the essence of the learning content
2. Is specific enough for AI image generation
3. Follows educational design best practices
4. Includes visual elements appropriate for learning

Output ONLY the description, no additional text.
""")
        return "\n".join(prompt_parts)


# ---------------------------------------------------------------------------
# 便捷函数（供 backend/main.py 调用）
# ---------------------------------------------------------------------------

def generate_learning_image_with_llm(
    llm,
    learning_content: str,
    image_type: str = "mind_map",
    style: str = "educational",
    size: str = "1024x1024",
    learning_path: Optional[Dict] = None,
    knowledge_points: Optional[str] = None,
    use_llm_enhancement: bool = True,
    image_mode: str = "search",         # "search" | "dalle" | "doubao"
    search_query: Optional[str] = None,
    prompt_is_ready: bool = False
) -> Dict[str, Any]:
    """
    生成学习相关图像的便捷函数

    Args:
        llm: LangChain LLM 实例
        learning_content: 学习内容描述
        image_type: 图像类型
        style: 视觉风格（搜索模式下不影响结果）
        size: 图像尺寸（仅 DALL-E/豆包 模式有效）
        learning_path: 学习路径信息
        knowledge_points: 知识点列表
        use_llm_enhancement: 是否使用 LLM 增强关键词/描述
        image_mode: 图像获取模式 ("search" | "dalle" | "doubao")

    Returns:
        Dict containing generated image info
    """
    generator = LearningImageGenerator(image_mode=image_mode)

    if use_llm_enhancement:
        return generator.generate_with_llm_description(
            llm=llm,
            learning_content=learning_content,
            learning_path=learning_path,
            knowledge_points=knowledge_points,
            image_type=image_type,
            style=style,
            size=size
        )
    else:
        return generator.generate_image(
            learning_content=learning_content,
            image_type=image_type,
            style=style,
            size=size,
            llm=llm,
            search_query=search_query,
            prompt_is_ready=prompt_is_ready
        )
