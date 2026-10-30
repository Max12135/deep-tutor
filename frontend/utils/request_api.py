import json
import httpx
import streamlit as st
from config import backend_endpoint, use_mock_data, use_search, api_timeout

def _safe_serialize(value):
    """将值安全地序列化为 JSON 字符串，避免 Python str() 产生的单引号格式"""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)

API_NAMES = {
    "chat_with_tutor": "chat-with-tutor",
    "refine_goal": "refine-learning-goal",
    "identify_skill_gap": "identify-skill-gap-with-info",
    "create_profile": "create-learner-profile-with-info",
    "update_profile": "update-learner-profile",
    "schedule_path": "schedule-learning-path",
    "reschedule_path": "reschedule-learning-path",
    "explore_knowledge_perspectives": "explore-knowledge-perspectives",
    "draft_knowledge_perspective": "draft-knowledge-perspective",
    "draft_point_perspectives": "draft-point-perspectives",
    "integrate_knowledge_document": "integrate-knowledge-document",
    "tailor_learning_content": "tailor-learning-content",
    "explore_knowledge_points": "explore-knowledge-points",
    "draft_knowledge_point": "draft-knowledge-point",
    "draft_knowledge_points": "draft-knowledge-points",
    "integrate_learning_document": "integrate-learning-document",
    "generate_document_quizzes": "generate-document-quizzes",
    "analyze_document_quiz": "analyze-document-quiz",
    "generate_followup_learning_round": "generate-followup-learning-round",
    "generate_learning_image": "generate-learning-image",
    "generate_knowledge_graph": "generate-knowledge-graph",
    "update_knowledge_graph_progress": "update-knowledge-graph-progress",
    "generate_knowledge_point_image": "generate-knowledge-point-image",
    "generate_session_images": "generate-session-images",
}


def make_post_request(api_name, data, mock_data_path=None, timeout=None):
    """Send a POST request to the backend API, or return mock data if enabled."""
    if use_mock_data and mock_data_path:
        try:
            with open(mock_data_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            st.error(f"加载模拟数据失败: {e}")
            return None

    if timeout is None:
        timeout = api_timeout
    # 运行时解析后端地址：优先读会话中的设置，允许用户在界面上改端口/主机而无需重启；
    # 统一补齐结尾斜杠，避免拼出 127.0.0.1:5000chat-with-tutor 这类错误 URL。
    base = st.session_state.get("backend_endpoint") or backend_endpoint
    if not str(base).endswith("/"):
        base = f"{base}/"
    backend_url = f"{base}{api_name}"
    try:
        response = httpx.post(backend_url, json=data, timeout=timeout)

        if response.status_code == 200:
            return response.json()
        else:
            # 记录详细错误并显式提示用户，避免"点了没反应"的错觉
            error_detail = response.text[:200] if response.text else "无详细信息"
            print(f"[API Error] {api_name}: Status {response.status_code}, Detail: {error_detail}")
            st.error(f"请求失败（{api_name}）：后端返回 HTTP {response.status_code}。{error_detail}")
            return None
    except httpx.TimeoutException:
        print(f"[API Error] {api_name}: Request timeout after {timeout} seconds")
        st.warning(f"请求超时（{timeout} 秒），请稍后重试。")
        return None
    except httpx.ConnectError:
        print(f"[API Error] {api_name}: Cannot connect to backend at {backend_url}")
        st.error("无法连接到后端服务，请确保后端已启动。")
        return None
    except Exception as e:
        print(f"[API Error] {api_name}: {type(e).__name__}: {e}")
        st.error(f"请求出错（{api_name}）：{type(e).__name__}。请查看后端日志。")
        return None

def get_available_models(backend_endpoint):
    backend_url = f"{backend_endpoint}list-llm-models"
    try:
        response = httpx.get(backend_url, timeout=30)
        if response.status_code == 200:
            return response.json().get("models", [])
        else:
            # st.write("Failed to fetch available models. Status code:", response.status_code)
            return []
    except Exception as e:
        # st.write("Failed to fetch available models. Error:", e)
        return []

def chat_with_tutor(chat_messages, learner_profile, llm_type="gpt4o", method_name="genmentor"):
    data = {
        "messages": _safe_serialize(chat_messages),
        "learner_profile": _safe_serialize(learner_profile),
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request(API_NAMES["chat_with_tutor"], data, "./assets/data_example/ai_tutor_chat.json")
    return response.get("response") if response else None

def refine_learning_goal(learning_goal, learner_information, llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learning_goal": str(learning_goal),
        "learner_information": str(learner_information),
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request(API_NAMES["refine_goal"], data)
    # 失败返回 None，由调用方决定是否保留原目标；不要返回占位字符串，否则会覆盖用户输入
    return response.get("refined_goal") if response else None

def identify_skill_gap(learning_goal, learner_information, llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learning_goal": str(learning_goal),
        "learner_information": str(learner_information),
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request(API_NAMES["identify_skill_gap"], data, "./assets/data_example/skill_gap.json")
    return response.get("skill_gaps") if response else None

def create_learner_profile(learning_goal, learner_information, skill_gaps, llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learning_goal": str(learning_goal),
        "learner_information": str(learner_information),
        "skill_gaps": _safe_serialize(skill_gaps),
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request(API_NAMES["create_profile"], data, "./assets/data_example/learner_profile.json")
    return response.get("learner_profile") if response else None

def update_learner_profile(learner_profile, learner_interactions, learner_information="", session_information="", llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learner_profile": _safe_serialize(learner_profile),
        "learner_interactions": _safe_serialize(learner_interactions),
        "learner_information": str(learner_information),
        "session_information": _safe_serialize(session_information),
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    # 画像更新由 LLM 重写整个画像，耗时较长，超时放宽到 2 倍
    update_timeout = api_timeout * 2
    response = make_post_request(API_NAMES["update_profile"], data, mock_data_path="./assets/data_example/learner_profile.json", timeout=update_timeout)
    return response.get("learner_profile") if response else None

# @st.cache_resource
def schedule_learning_path(learner_profile, session_count, llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learner_profile": _safe_serialize(learner_profile),
        "session_count": session_count,
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request(API_NAMES["schedule_path"], data, "./assets/data_example/learning_path.json")
    return response.get("learning_path") if response else None

def reschedule_learning_path(learning_path, learner_profile, session_count, other_feedback="", llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learning_path": _safe_serialize(learning_path),
        "learner_profile": _safe_serialize(learner_profile),
        "session_count": int(session_count),
        "other_feedback": str(other_feedback),
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request(API_NAMES["reschedule_path"], data, "./assets/data_example/learning_path.json")
    return response.get("learning_path") if response else None

# @st.cache_resource
def generate_document_quizzes(learner_profile, learning_document, single_choice_count, multiple_choice_count, true_false_count, short_answer_count, quiz_blueprint=None, generation_focus="", llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learner_profile": _safe_serialize(learner_profile),
        "learning_document": _safe_serialize(learning_document),
        "single_choice_count": single_choice_count,
        "multiple_choice_count": multiple_choice_count,
        "true_false_count": true_false_count,
        "short_answer_count": short_answer_count,
        "quiz_blueprint": _safe_serialize(quiz_blueprint or []),
        "generation_focus": str(generation_focus or ""),
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request(API_NAMES["generate_document_quizzes"], data, "./assets/data_example/document_quiz.json")
    return response.get("document_quiz") if response else None


def analyze_document_quiz(learner_profile, quiz_attempts, session_information="", llm_type="gpt4o", method_name="genmentor"):
    """提交测验作答记录，由后端 LLM 生成学习诊断（掌握点/薄弱点/建议/逐题判定）。"""
    data = {
        "learner_profile": _safe_serialize(learner_profile),
        "quiz_attempts": _safe_serialize(quiz_attempts),
        "session_information": _safe_serialize(session_information),
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    # 诊断由 LLM 生成，使用较长超时
    response = make_post_request(API_NAMES["analyze_document_quiz"], data, "./assets/data_example/quiz_analysis.json", timeout=api_timeout * 2)
    return response.get("quiz_analysis") if response else None


def generate_followup_learning_round(learner_profile, learning_path, learning_session, quiz_attempts, quiz_analysis, previous_quiz, mode="A", round_index=1, allow_parallel=True, use_search=True, llm_type="gpt4o", method_name="genmentor"):
    """基于诊断结果生成下一轮学习内容（模式A补强内容/模式B回顾）+ 蓝图式新测验。"""
    data = {
        "learner_profile": _safe_serialize(learner_profile),
        "learning_path": _safe_serialize(learning_path),
        "learning_session": _safe_serialize(learning_session),
        "quiz_attempts": _safe_serialize(quiz_attempts),
        "quiz_analysis": _safe_serialize(quiz_analysis),
        "previous_quiz": _safe_serialize(previous_quiz),
        "mode": str(mode),
        "round_index": int(round_index),
        "allow_parallel": bool(allow_parallel),
        "use_search": bool(use_search),
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    # 模式 A 串行执行 探索→起草→整合→出题 多次 LLM 调用，超时进一步放宽
    response = make_post_request(API_NAMES["generate_followup_learning_round"], data, timeout=api_timeout * 4)
    return response.get("followup_learning_round") if response else None

# @st.cache_resource
def explore_knowledge_points(learner_profile, learning_path, learning_session, llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learner_profile": _safe_serialize(learner_profile),
        "learning_path": _safe_serialize(learning_path),
        "learning_session": _safe_serialize(learning_session),
    }
    response = make_post_request("explore-knowledge-points", data, "./assets/data_example/knowledge_points.json")
    return response.get("knowledge_points") if response else None

# @st.cache_resource
def draft_knowledge_point(learner_profile, learning_path, learning_session, knowledge_points, knowledge_point, use_search, llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learner_profile": _safe_serialize(learner_profile),
        "learning_path": _safe_serialize(learning_path),
        "learning_session": _safe_serialize(learning_session),
        "knowledge_points": _safe_serialize(knowledge_points),
        "knowledge_point": _safe_serialize(knowledge_point),
        "use_search": use_search,
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request("draft-knowledge-point", data, "./assets/data_example/knowledge_point.json")
    return response.get("knowledge_draft") if response else None

# @st.cache_resource
def draft_knowledge_points(learner_profile, learning_path, learning_session, knowledge_points, allow_parallel, use_search, llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learner_profile": _safe_serialize(learner_profile),
        "learning_path": _safe_serialize(learning_path),
        "learning_session": _safe_serialize(learning_session),
        "knowledge_points": _safe_serialize(knowledge_points),
        "allow_parallel": allow_parallel,
        "use_search": use_search,
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request("draft-knowledge-points", data, "./assets/data_example/knowledge_points.json")
    return response.get("knowledge_drafts") if response else None

# @st.cache_resource
def integrate_learning_document(learner_profile, learning_path, learning_session, knowledge_points, knowledge_drafts, output_markdown=False, llm_type="gpt4o", method_name="genmentor"):
    data = {
        "learner_profile": _safe_serialize(learner_profile),
        "learning_path": _safe_serialize(learning_path),
        "learning_session": _safe_serialize(learning_session),
        "knowledge_points": _safe_serialize(knowledge_points),
        "knowledge_drafts": _safe_serialize(knowledge_drafts),
        "output_markdown": output_markdown,
        "llm_type": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request("integrate-learning-document", data, "./assets/data_example/learning_document.json")
    if output_markdown:
        return response.get("learning_document") if response else None
    else:
        return response.get("learning_document") if response else None


def generate_learning_image(
    learning_content: str,
    image_type: str = "mind_map",
    style: str = "educational",
    size: str = "1024x1024",
    llm_type: str = "gpt4o",
    method_name: str = "genmentor",
    image_mode: str = "search"  # search | dalle | doubao
):
    """生成学习相关的图像（多模态内容生成）

    Args:
        learning_content: 学习内容描述，用于生成图像
        image_type: 图像类型 (knowledge_tree, mind_map, concept_diagram, summary_poster, learning_roadmap)
        style: 视觉风格 (educational, cartoon, minimalist, detailed, infographic, sketch)
        size: 图像尺寸 (1024x1024, 1792x1024, 1024x1792)
        llm_type: LLM 类型
        method_name: 方法名称
        image_mode: 图像生成模式 (search: 必应搜索, dalle: OpenAI DALL-E, doubao: 豆包/火山引擎)

    Returns:
        Dict containing:
        - image_url: 生成的图像 URL
        - prompt: 使用的提示词
        - image_type: 图像类型
        - success: 是否成功
    """
    data = {
        "learning_content": str(learning_content),
        "image_type": str(image_type),
        "style": str(style),
        "size": str(size),
        "model_provider": "deepseek",
        "model_name": "deepseek-chat",
        "method_name": str(method_name),
        "image_mode": str(image_mode),
    }
    # 图像生成需要更长的超时时间
    image_timeout = api_timeout * 6
    response = make_post_request("generate-learning-image", data, timeout=image_timeout)
    return response


def generate_knowledge_graph(
    knowledge_points,
    session_title: str = "",
    session_abstract: str = "",
    llm_type: str = "gpt4o",
    method_name: str = "genmentor"
):
    """生成学习进度知识图谱

    Args:
        knowledge_points: 知识点列表
        session_title: 学习会话标题
        session_abstract: 学习会话摘要
        llm_type: LLM 类型
        method_name: 方法名称

    Returns:
        Dict containing:
        - nodes: 节点列表
        - edges: 边列表
        - layout: 布局配置
    """
    data = {
        "knowledge_points": _safe_serialize(knowledge_points),
        "session_title": str(session_title),
        "session_abstract": str(session_abstract),
        "model_provider": "deepseek",
        "model_name": "deepseek-chat",
        "method_name": str(method_name),
    }
    response = make_post_request("generate-knowledge-graph", data, timeout=60)
    return response


def update_knowledge_graph_progress(
    graph_data,
    node_id: str,
    status: str = "completed",
    llm_type: str = "gpt4o",
    method_name: str = "genmentor"
):
    """更新知识图谱节点状态

    Args:
        graph_data: 图谱数据
        node_id: 节点ID
        status: 新状态 (unlearned, in_progress, completed)
        llm_type: LLM 类型
        method_name: 方法名称

    Returns:
        Dict containing updated graph data
    """
    data = {
        "graph_data": str(graph_data),
        "node_id": str(node_id),
        "status": str(status),
        "model_provider": str(llm_type),
        "model_name": str(llm_type),
        "method_name": str(method_name),
    }
    response = make_post_request("update-knowledge-graph-progress", data, timeout=30)
    return response


def generate_knowledge_point_image(
    knowledge_point,
    session_title: str = "",
    session_abstract: str = "",
    knowledge_description: str = "",
    visual_style: str = "educational",
    size: str = "1024x1024",
    llm_type: str = "gpt4o",
    method_name: str = "genmentor"
):
    """为单个知识点生成可视化图片

    Args:
        knowledge_point: 知识点数据
        session_title: 学习会话标题
        session_abstract: 学习会话摘要
        knowledge_description: 详细的知识描述
        visual_style: 可视化风格 (educational, realistic, diagrammatic, infographic, minimalist, colorful)
        size: 图像尺寸 (1024x1024, 1792x1024, 1024x1792)
        llm_type: LLM 类型
        method_name: 方法名称

    Returns:
        Dict containing:
        - image_url: 生成的图像 URL
        - prompt: 使用的提示词
        - knowledge_point_id: 知识点 ID
        - knowledge_point_name: 知识点名称
        - visual_style: 使用的视觉风格
        - success: 是否成功
    """
    data = {
        "knowledge_point": _safe_serialize(knowledge_point),
        "session_title": str(session_title),
        "session_abstract": str(session_abstract),
        "knowledge_description": str(knowledge_description),
        "visual_style": str(visual_style),
        "size": str(size),
        "model_provider": "deepseek",
        "model_name": "deepseek-chat",
        "method_name": str(method_name),
    }
    # 图片生成需要更长的超时时间
    image_timeout = api_timeout * 6
    response = make_post_request("generate-knowledge-point-image", data, timeout=image_timeout)
    return response


def generate_session_images(
    knowledge_points,
    session_title: str = "",
    session_abstract: str = "",
    visual_style: str = "educational",
    size: str = "1024x1024",
    max_images: int = 5,
    llm_type: str = "gpt4o",
    method_name: str = "genmentor"
):
    """为学习会话的所有知识点生成可视化图片

    Args:
        knowledge_points: 知识点列表
        session_title: 学习会话标题
        session_abstract: 学习会话摘要
        visual_style: 可视化风格
        size: 图像尺寸
        max_images: 最多生成多少张图片
        llm_type: LLM 类型
        method_name: 方法名称

    Returns:
        Dict containing:
        - images: 图片生成结果列表
    """
    data = {
        "knowledge_points": _safe_serialize(knowledge_points),
        "session_title": str(session_title),
        "session_abstract": str(session_abstract),
        "visual_style": str(visual_style),
        "size": str(size),
        "max_images": int(max_images),
        "model_provider": "deepseek",
        "model_name": "deepseek-chat",
        "method_name": str(method_name),
    }
    # 批量生成需要更长的超时时间
    batch_timeout = api_timeout * 12
    response = make_post_request("generate-session-images", data, timeout=batch_timeout)
    return response

