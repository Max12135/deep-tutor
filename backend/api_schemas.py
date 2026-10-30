
from pydantic import BaseModel
from typing import Optional


class BaseRequest(BaseModel):
    model_provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    method_name: str = "genmentor"


class ChatWithAutorRequest(BaseRequest):

    messages: str
    learner_profile: str = ""


class LearningGoalRefinementRequest(BaseRequest):

    learning_goal: str
    learner_information: str = ""


class SkillGapIdentificationRequest(BaseRequest):

    learning_goal: str
    learner_information: str
    skill_requirements: Optional[str] = None


class LearnerProfileInitializationWithInfoRequest(BaseRequest):

    learning_goal: str
    learner_information: str
    skill_gaps: str


class LearnerProfileInitializationRequest(BaseRequest):

    learning_goal: str
    skill_requirements: str
    skill_gaps: str
    cv_path: str


class LearnerProfileUpdateRequest(BaseRequest):

    learner_profile: str
    learner_interactions: str
    learner_information: str = ""
    session_information: str = ""


class LearningPathSchedulingRequest(BaseRequest):

    learner_profile: str
    session_count: int


class LearningPathReschedulingRequest(BaseRequest):
    
    learner_profile: str
    learning_path: str
    session_count: int = -1
    other_feedback: str = ""


class KnowledgeDocumentIntegrationRequest(BaseRequest):
    """整合学习文档请求。字段需与 frontend/utils/request_api.py 及 main.py 的 handler 保持一致。"""

    learner_profile: str
    learning_path: str
    learning_session: str
    knowledge_points: str
    knowledge_drafts: str
    output_markdown: bool = True


class KnowledgeQuizGenerationRequest(BaseModel):

    learner_profile: str
    learning_document: str
    single_choice_count: int = 3
    multiple_choice_count: int = 0
    true_false_count: int = 0
    short_answer_count: int = 0
    quiz_blueprint: str = ""
    generation_focus: str = ""


class QuizAnalysisRequest(BaseModel):

    learner_profile: str
    quiz_attempts: str
    session_information: str = ""


class FollowupLearningRoundRequest(BaseModel):

    learner_profile: str
    learning_path: str
    learning_session: str
    quiz_attempts: str
    quiz_analysis: str
    previous_quiz: str
    mode: str = "A"
    round_index: int = 1
    allow_parallel: bool = True
    use_search: bool = True


class TailoredContentGenerationRequest(BaseModel):

    learner_profile: str
    learning_path: str
    learning_session: str
    use_search: bool = True
    allow_parallel: bool = True
    with_quiz: bool = True


class KnowledgePointExplorationRequest(BaseModel):
    
    learner_profile: str
    learning_path: str
    learning_session: str


class KnowledgePointDraftingRequest(BaseModel):

    learner_profile: str
    learning_path: str
    learning_session: str
    knowledge_points: str
    knowledge_point: str
    use_search: bool


class KnowledgePointsDraftingRequest(BaseModel):

    learner_profile: str
    learning_path: str
    learning_session: str
    knowledge_points: str
    use_search: bool
    allow_parallel: bool


class LearningImageGenerationRequest(BaseModel):

    model_provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    method_name: str = "genmentor"

    # 学习内容描述，用于生成图像的提示词
    learning_content: str
    # 图像类型：knowledge_tree(知识树), mind_map(思维导图), concept_diagram(概念图), summary_poster(总结海报)
    image_type: str = "mind_map"
    # 图像生成模式：search(必应搜索), dalle(OpenAI DALL-E), doubao(豆包/火山引擎)
    image_mode: str = "search"
    # 额外的图像生成参数
    style: str = "educational"  # educational, cartoon, minimalist, detailed
    size: str = "1024x1024"  # 1024x1024, 1792x1024, 1024x1792


class KnowledgeGraphGenerationRequest(BaseModel):
    """知识图谱生成请求"""

    model_provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    method_name: str = "genmentor"

    # 知识点列表
    knowledge_points: str
    # 学习会话标题
    session_title: str = ""
    # 学习会话摘要
    session_abstract: str = ""


class KnowledgeGraphUpdateRequest(BaseModel):
    """知识图谱状态更新请求"""

    graph_data: str
    node_id: str
    status: str = "completed"  # unlearned, in_progress, completed


class KnowledgePointImageGenerationRequest(BaseModel):
    """知识点图片生成请求"""

    model_provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    method_name: str = "genmentor"

    # 知识点信息
    knowledge_point: str  # JSON 字符串
    session_title: str = ""
    session_abstract: str = ""
    knowledge_description: str = ""

    # 可视化参数
    visual_style: str = "educational"  # educational, realistic, diagrammatic, infographic, minimalist, colorful
    size: str = "1024x1024"


class SessionImagesGenerationRequest(BaseModel):
    """学习会话图片批量生成请求"""

    model_provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    method_name: str = "genmentor"

    # 知识点信息
    knowledge_points: str  # JSON 数组字符串
    session_title: str = ""
    session_abstract: str = ""

    # 可视化参数
    visual_style: str = "educational"
    size: str = "1024x1024"
    max_images: int = 5  # 最多生成多少张图片
