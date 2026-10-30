import json
import logging
import time
import os
import uvicorn
import aiofiles
import hydra
from omegaconf import DictConfig, OmegaConf
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Request
from base.llm_factory import LLMFactory
from base.searcher_factory import SearchRunner
from base.search_rag import SearchRagManager
from utils.preprocess import extract_text_from_pdf
from fastapi.responses import JSONResponse
from modules.skill_gap_identification import *
from modules.adaptive_learner_modeling import *
from modules.personalized_resource_delivery import *
from modules.ai_chatbot_tutor import chat_with_tutor_with_llm
from modules.personalized_resource_delivery.image_generator import generate_learning_image_with_llm
from modules.personalized_resource_delivery.knowledge_graph_generator import (
    generate_knowledge_graph_with_llm,
    update_graph_progress,
)
from modules.personalized_resource_delivery.knowledge_point_image_generator import (
    generate_knowledge_point_image_with_llm,
    generate_session_images_with_llm,
    get_doubao_fallback_notice,
)
from modules.personalized_resource_delivery.agents.document_quiz_analyzer import analyze_document_quiz_with_llm
from modules.personalized_resource_delivery.agents.followup_learning_round import generate_followup_learning_round_with_llm
from api_schemas import *
from config import load_config
from utils.parsers import safe_parse

app_config = load_config(config_name="main")

# 配置上传目录（跨平台兼容）
upload_config = app_config.get("upload", {})
UPLOAD_LOCATION = os.path.join(os.getcwd(), upload_config.get("location", "data/cv"))
os.makedirs(UPLOAD_LOCATION, exist_ok=True)

_search_rag_manager = None


def get_search_rag_manager():
    """懒加载全局 SearchRagManager 单例（embedding 模型只加载一次，避免每次请求重复加载）。"""
    global _search_rag_manager
    if _search_rag_manager is None:
        try:
            _search_rag_manager = SearchRagManager.from_config(app_config)
        except Exception as e:
            logger.warning(f"SearchRagManager 初始化失败（RAG 增强将不可用）: {e}")
    return _search_rag_manager

app = FastAPI(
    title="DeepTutor API",
    version="1.0.0",
    description="Personalized Learning Path Planning Assistant API"
)

# 配置 CORS（从环境变量或配置文件读取）
api_config = app_config.get("api", {})
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    api_config.get("cors_origins", "http://localhost:8501,http://127.0.0.1:8501")
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 请求体大小限制 (10MB)
MAX_UPLOAD_SIZE = 10 * 1024 * 1024

@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    """限制上传文件大小"""
    if request.method in ["POST", "PUT", "PATCH"]:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_UPLOAD_SIZE:
            return JSONResponse(
                status_code=413,
                content={"detail": "Payload too large. Maximum size is 10MB."}
            )
    response = await call_next(request)
    return response

# 配置日志
logger = logging.getLogger(__name__)

_KNOWN_LLM_PROVIDERS = {
    "openai", "anthropic", "deepseek", "ollama", "together",
    "azure-openai", "azure_openai", "groq", "cohere", "mistralai",
    "fireworks", "nvidia", "xai", "google-genai", "google_genai",
}

def get_llm(model_provider: str | None = None, model_name: str | None = None, **kwargs):
    # 如果前端传来的 model_provider 不是合法的 provider（例如 "gpt4o"），
    # 则 fallback 到配置文件中的默认 LLM，避免 500 错误
    if model_provider and model_provider.lower() not in _KNOWN_LLM_PROVIDERS:
        logger.warning(f"Unknown model_provider '{model_provider}', falling back to default LLM config")
        model_provider = None
        model_name = None
    model_provider = model_provider or "deepseek"
    model_name = model_name or "deepseek-reasoner"
    return LLMFactory.create(model=model_name, model_provider=model_provider, **kwargs)


def get_fast_llm(**kwargs):
    """全部结构化 LLM 任务统一用快速模型（deepseek-chat）。

    实测各任务（路径规划/探索/起草/整合/出题/诊断/画像）用 chat 版质量足够，
    速度比 deepseek-reasoner 快 3-5 倍且更便宜。如需单个任务回退 reasoner，
    把对应端点的 get_fast_llm() 改回 get_llm() 即可。

    默认把输出上限提到 8192（deepseek-chat 的最大值，默认为 4096）：
    整合/起草这类要输出整篇长 JSON 的任务，4096 会在字符串中间被硬截断，
    截断后解析器可能捡到正文里的碎片，返回形状错误的结果，最终表现为 500。
    max_tokens 只是上限、不是目标，短输出不受影响、不会变慢。
    """
    kwargs.setdefault("max_tokens", 8192)
    return get_llm("deepseek", "deepseek-chat", **kwargs)

@app.get("/list-llm-models")
def list_llm_models():
    try:
        return {"models": [
            {
                "model_name": app_config.llm.model_name, 
                "model_provider": app_config.llm.provider
            }
        ]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/chat-with-tutor")
def chat_with_autor(request: ChatWithAutorRequest):
    llm = get_llm(request.model_provider, request.model_name)
    learner_profile = request.learner_profile
    try:
        converted_messages = safe_parse(request.messages)
        if not isinstance(converted_messages, list):
            return JSONResponse(
                status_code=400,
                content={"detail": "messages must be a JSON array"}
            )
        response = chat_with_tutor_with_llm(
            llm,
            converted_messages,
            learner_profile,
            search_rag_manager=get_search_rag_manager(),
            use_search=True,
        )
        return {"response": response}
    except Exception as e:
        logger.error(f"Error in chat-with-tutor: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/refine-learning-goal")
def refine_learning_goal(request: LearningGoalRefinementRequest):
    llm = get_llm(request.model_provider, request.model_name)
    try:
        refined_learning_goal = refine_learning_goal_with_llm(llm, request.learning_goal, request.learner_information)
        return refined_learning_goal
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/identify-skill-gap-with-info")
def identify_skill_gap_with_info(request: SkillGapIdentificationRequest):
    llm = get_llm(request.model_provider, request.model_name)
    learning_goal = request.learning_goal
    learner_information = request.learner_information
    skill_requirements = request.skill_requirements
    try:
        skill_requirements = safe_parse(skill_requirements)
        if skill_requirements and not isinstance(skill_requirements, dict):
            skill_requirements = None

        skill_gaps, skill_requirements = identify_skill_gap_with_llm(
            llm, learning_goal, learner_information, skill_requirements
        )
        results = {**skill_gaps, **(skill_requirements or {})}
        return results
    except Exception as e:
        logger.error(f"Error in identify-skill-gap-with-info: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.post("/identify-skill-gap")
async def identify_skill_gap(goal: str = Form(...), cv: UploadFile = File(...), model_provider: str = Form("deepseek"), model_name: str = Form("deepseek-chat")):
    llm = get_llm(model_provider, model_name)
    mapper = SkillRequirementMapper(llm)
    skill_gap_identifier = SkillGapIdentifier(llm)
    try:
        # 安全的文件名：先取 basename 去掉任何目录成分，再白名单限定为 pdf，
        # 防止 ../../ 路径穿越写入到上传目录之外。
        filename = os.path.basename(cv.filename or "")
        if not filename or ".." in filename:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid filename"}
            )
        if not filename.lower().endswith(".pdf"):
            return JSONResponse(
                status_code=400,
                content={"detail": "Only PDF files are supported"}
            )

        file_location = os.path.join(UPLOAD_LOCATION, filename)

        # 异步写入文件
        content = await cv.read()
        async with aiofiles.open(file_location, "wb") as file_object:
            await file_object.write(content)

        cv_text = extract_text_from_pdf(file_location)  
        skill_requirements = mapper.map_goal_to_skill({
            "learning_goal": goal
        })
        skill_gaps = skill_gap_identifier.identify_skill_gap({
            "learning_goal": goal,
            "skill_requirements": skill_requirements,
            "learner_information": cv_text
        })
        results = {**skill_gaps, **skill_requirements}
        return results
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/create-learner-profile-with-info")
def create_learner_profile_with_info(request: LearnerProfileInitializationWithInfoRequest):
    llm = get_llm(request.model_provider, request.model_name)
    learner_information = request.learner_information
    learning_goal = request.learning_goal
    skill_gaps = request.skill_gaps
    try:
        learner_information = safe_parse(learner_information, {"raw": learner_information})
        skill_gaps = safe_parse(skill_gaps, {"raw": skill_gaps})

        learner_profile = initialize_learner_profile_with_llm(
            llm, learning_goal, learner_information, skill_gaps
        )
        # 强制保证 learning_goal 与用户输入一致，防止 LLM 擅自修改
        if isinstance(learner_profile, dict):
            learner_profile["learning_goal"] = learning_goal
        return {"learner_profile": learner_profile}
    except Exception as e:
        logger.error(f"Error in create-learner-profile-with-info: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create-learner-profile")
def create_learner_profile(request: LearnerProfileInitializationRequest):
    llm = get_llm(request.model_provider, request.model_name)
    # 同样只允许上传目录内的 pdf 文件名，杜绝通过 cv_path 做路径穿越
    cv_name = os.path.basename(str(request.cv_path or ""))
    if not cv_name or ".." in cv_name or not cv_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid cv_path")
    file_location = os.path.join(UPLOAD_LOCATION, cv_name)
    learner_information = extract_text_from_pdf(file_location)
    learning_goal = request.learning_goal
    skill_gaps = request.skill_gaps
    try:
        if isinstance(skill_gaps, str):
            try:
                skill_gaps = json.loads(skill_gaps)
            except Exception:
                skill_gaps = {"raw": skill_gaps}
        learner_profile = initialize_learner_profile_with_llm(
            llm, learning_goal, {"raw": learner_information}, skill_gaps
        )
        return {"learner_profile": learner_profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update-learner-profile")
def update_learner_profile(request: LearnerProfileUpdateRequest):
    llm = get_llm(request.model_provider, request.model_name)
    learner_profile = request.learner_profile
    learner_interactions = request.learner_interactions
    learner_information = request.learner_information
    session_information = request.session_information
    try:
        learner_profile = safe_parse(learner_profile, {})
        learner_interactions = safe_parse(learner_interactions, {})
        learner_information = safe_parse(learner_information, "")
        session_information = safe_parse(session_information, "")

        learner_profile = update_learner_profile_with_llm(
            llm,
            learner_profile,
            learner_interactions,
            learner_information,
            session_information,
        )
        return {"learner_profile": learner_profile}
    except Exception as e:
        logger.error(f"Error in update-learner-profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/schedule-learning-path")
def schedule_learning_path(request: LearningPathSchedulingRequest):
    llm = get_llm(request.model_provider, request.model_name)
    learner_profile = request.learner_profile
    session_count = request.session_count
    try:
        learner_profile = safe_parse(learner_profile, {})
        if not isinstance(learner_profile, dict):
            learner_profile = {}
        learning_path = schedule_learning_path_with_llm(llm, learner_profile, session_count)
        return learning_path
    except Exception as e:
        logger.error(f"Error in schedule-learning-path: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reschedule-learning-path")
def reschedule_learning_path(request: LearningPathReschedulingRequest):
    llm = get_llm(request.model_provider, request.model_name)
    learner_profile = request.learner_profile
    learning_path = request.learning_path
    session_count = request.session_count
    other_feedback = request.other_feedback
    try:
        learner_profile = safe_parse(learner_profile, {})
        if not isinstance(learner_profile, dict):
            learner_profile = {}
        learning_path = safe_parse(learning_path, [])
        if not isinstance(learning_path, list):
            learning_path = []
        if isinstance(other_feedback, str) and other_feedback.strip():
            try:
                other_feedback = safe_parse(other_feedback, other_feedback)
            except Exception:
                pass
        learning_path = reschedule_learning_path_with_llm(
            llm, learning_path, learner_profile, session_count, other_feedback
        )
        return learning_path
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/explore-knowledge-points")
def explore_knowledge_points(request: KnowledgePointExplorationRequest):
    llm = get_fast_llm()
    learner_profile = request.learner_profile
    learning_path = request.learning_path
    learning_session = request.learning_session

    learner_profile = safe_parse(learner_profile, {})
    learning_path = safe_parse(learning_path, {})
    learning_session = safe_parse(learning_session, {})

    try:
        knowledge_points = explore_knowledge_points_with_llm(llm, learner_profile, learning_path, learning_session)
        return knowledge_points
    except Exception as e:
        logger.error(f"Error in explore-knowledge-points: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/draft-knowledge-point")
def draft_knowledge_point(request: KnowledgePointDraftingRequest):
    llm = get_fast_llm()
    learner_profile = request.learner_profile
    learning_path = request.learning_path
    learning_session = request.learning_session
    knowledge_points = request.knowledge_points
    knowledge_point = request.knowledge_point
    use_search = request.use_search
    try:
        knowledge_draft = draft_knowledge_point_with_llm(llm, learner_profile, learning_path, learning_session, knowledge_points, knowledge_point, use_search, search_rag_manager=get_search_rag_manager())
        return {"knowledge_draft": knowledge_draft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/draft-knowledge-points")
def draft_knowledge_points(request: KnowledgePointsDraftingRequest):
    llm = get_fast_llm()
    learner_profile = request.learner_profile
    learning_path = request.learning_path
    learning_session = request.learning_session
    knowledge_points = request.knowledge_points
    use_search = request.use_search
    allow_parallel = request.allow_parallel
    try:
        knowledge_drafts = draft_knowledge_points_with_llm(
            llm, learner_profile, learning_path, learning_session,
            knowledge_points, allow_parallel, use_search,
            search_rag_manager=get_search_rag_manager()
        )
        return {"knowledge_drafts": knowledge_drafts}
    except Exception as e:
        logger.error(f"Error in draft-knowledge-points: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/integrate-learning-document")
def integrate_learning_document(request: KnowledgeDocumentIntegrationRequest):
    llm = get_fast_llm()
    learner_profile = request.learner_profile
    learning_path = request.learning_path
    learning_session = request.learning_session
    knowledge_points = request.knowledge_points
    knowledge_drafts = request.knowledge_drafts
    output_markdown = request.output_markdown
    try:
        learning_document = integrate_learning_document_with_llm(
            llm, learner_profile, learning_path, learning_session,
            knowledge_points, knowledge_drafts, output_markdown
        )
        return {"learning_document": learning_document}
    except Exception as e:
        logger.error(f"Error in integrate-learning-document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-document-quizzes")
def generate_document_quizzes(request: KnowledgeQuizGenerationRequest):
    llm = get_fast_llm()
    learner_profile = request.learner_profile
    learning_document = request.learning_document
    single_choice_count = request.single_choice_count
    multiple_choice_count = request.multiple_choice_count
    true_false_count = request.true_false_count
    short_answer_count = request.short_answer_count
    quiz_blueprint = request.quiz_blueprint
    generation_focus = request.generation_focus
    try:
        parsed_blueprint = safe_parse(quiz_blueprint, [])
        if not isinstance(parsed_blueprint, list):
            parsed_blueprint = []
        document_quiz = generate_document_quizzes_with_llm(
            llm, learner_profile, learning_document,
            single_choice_count, multiple_choice_count, true_false_count, short_answer_count,
            quiz_blueprint=parsed_blueprint,
            generation_focus=generation_focus or "",
        )
        return {"document_quiz": document_quiz}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze-document-quiz")
def analyze_document_quiz(request: QuizAnalysisRequest):
    llm = get_fast_llm()
    learner_profile = request.learner_profile
    quiz_attempts = request.quiz_attempts
    session_information = request.session_information
    try:
        learner_profile = safe_parse(learner_profile, {})
        quiz_attempts = safe_parse(quiz_attempts, [])
        if not isinstance(quiz_attempts, list):
            quiz_attempts = []
        session_information = safe_parse(session_information, {})
        analysis = analyze_document_quiz_with_llm(
            llm,
            learner_profile,
            quiz_attempts,
            session_information=session_information,
        )
        return {"quiz_analysis": analysis}
    except Exception as e:
        logger.error(f"Error in analyze-document-quiz: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-followup-learning-round")
def generate_followup_learning_round(request: FollowupLearningRoundRequest):
    llm = get_fast_llm()
    try:
        learner_profile = safe_parse(request.learner_profile, {})
        learning_path = safe_parse(request.learning_path, [])
        learning_session = safe_parse(request.learning_session, {})
        quiz_attempts = safe_parse(request.quiz_attempts, [])
        if not isinstance(quiz_attempts, list):
            quiz_attempts = []
        quiz_analysis = safe_parse(request.quiz_analysis, {})
        previous_quiz = safe_parse(request.previous_quiz, {})

        followup_round = generate_followup_learning_round_with_llm(
            llm,
            learner_profile,
            learning_path,
            learning_session,
            quiz_attempts,
            quiz_analysis,
            previous_quiz,
            mode=request.mode,
            round_index=request.round_index,
            allow_parallel=request.allow_parallel,
            use_search=request.use_search,
        )
        return {"followup_learning_round": followup_round}
    except Exception as e:
        logger.error(f"Error in generate-followup-learning-round: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tailor-knowledge-content")
def tailor_knowledge_content(request: TailoredContentGenerationRequest):
    llm = get_fast_llm()
    learning_path = request.learning_path
    learner_profile = request.learner_profile
    learning_session = request.learning_session
    use_search = request.use_search
    allow_parallel = request.allow_parallel
    with_quiz = request.with_quiz
    try:
        tailored_content = create_learning_content_with_llm(
            llm, learner_profile, learning_path, learning_session, allow_parallel=allow_parallel, with_quiz=with_quiz, use_search=use_search
        )
        return {"tailored_content": tailored_content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-learning-image")
def generate_learning_image(request: LearningImageGenerationRequest):
    """多模态内容生成 - 生成学习相关图像"""
    llm = get_llm(request.model_provider, request.model_name)
    learning_content = request.learning_content
    image_type = request.image_type
    style = request.style
    size = request.size
    image_mode = request.image_mode  # search | dalle | doubao

    # 解析 learning_path 和 knowledge_points (如果作为字符串传递)
    learning_path = None
    knowledge_points = None

    try:
        if isinstance(learning_content, str) and learning_content.strip().startswith("{"):
            content_dict = json.loads(learning_content)
            learning_path = content_dict.get("learning_path")
            knowledge_points = content_dict.get("knowledge_points")
    except Exception:
        pass

    try:
        result = generate_learning_image_with_llm(
            llm=llm,
            learning_content=learning_content,
            image_type=image_type,
            style=style,
            size=size,
            learning_path=learning_path,
            knowledge_points=knowledge_points,
            use_llm_enhancement=True,
            image_mode=image_mode
        )
        return result
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-knowledge-graph")
def generate_knowledge_graph(request: KnowledgeGraphGenerationRequest):
    """生成学习进度知识图谱"""
    llm = get_llm(request.model_provider, request.model_name)

    try:
        # 解析知识点
        knowledge_points = safe_parse(request.knowledge_points, [])

        graph_data = generate_knowledge_graph_with_llm(
            llm=llm,
            knowledge_points=knowledge_points,
            session_title=request.session_title,
            session_abstract=request.session_abstract
        )
        return graph_data
    except Exception as e:
        logger.error(f"Error in generate-knowledge-graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/update-knowledge-graph-progress")
def update_knowledge_graph_progress(request: KnowledgeGraphUpdateRequest):
    """更新知识图谱节点状态"""
    try:
        # 解析图谱数据
        graph_data = safe_parse(request.graph_data, {})

        updated_graph = update_graph_progress(
            graph_data=graph_data,
            node_id=request.node_id,
            status=request.status
        )
        return updated_graph
    except Exception as e:
        logger.error(f"Error in update-knowledge-graph-progress: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-knowledge-point-image")
def generate_knowledge_point_image(request: KnowledgePointImageGenerationRequest):
    """为单个知识点生成可视化图片"""
    llm = get_llm(request.model_provider, request.model_name)

    try:
        # 解析知识点数据
        knowledge_point = safe_parse(request.knowledge_point, {})

        if not isinstance(knowledge_point, dict):
            return JSONResponse(
                status_code=400,
                content={"detail": "knowledge_point must be a valid JSON object"}
            )

        result = generate_knowledge_point_image_with_llm(
            llm=llm,
            knowledge_point=knowledge_point,
            session_title=request.session_title,
            session_abstract=request.session_abstract,
            knowledge_description=request.knowledge_description,
            visual_style=request.visual_style,
            size=request.size
        )
        return result
    except Exception as e:
        logger.error(f"Error in generate-knowledge-point-image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-session-images")
def generate_session_images(request: SessionImagesGenerationRequest):
    """为学习会话的所有知识点生成可视化图片"""
    llm = get_llm(request.model_provider, request.model_name)

    try:
        # 解析知识点列表
        knowledge_points = safe_parse(request.knowledge_points, [])

        if not isinstance(knowledge_points, list):
            return JSONResponse(
                status_code=400,
                content={"detail": "knowledge_points must be a valid JSON array"}
            )

        results = generate_session_images_with_llm(
            llm=llm,
            knowledge_points=knowledge_points,
            session_title=request.session_title,
            session_abstract=request.session_abstract,
            visual_style=request.visual_style,
            size=request.size,
            max_images=request.max_images
        )
        # 若豆包生图不可用已回退到必应搜索，把原因一并返回，便于前端明确提示
        return {"images": results, "notice": get_doubao_fallback_notice()}
    except Exception as e:
        logger.error(f"Error in generate-session-images: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    server_cfg = app_config.get("server", {})
    host = app_config.get("server", {}).get("host", "127.0.0.1")
    port = int(app_config.get("server", {}).get("port", 5000))
    log_level = str(app_config.get("log_level", "info")).lower()
    uvicorn.run(app, host=host, port=port, log_level=log_level)
