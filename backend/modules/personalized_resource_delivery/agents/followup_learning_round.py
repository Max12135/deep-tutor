from __future__ import annotations

import copy
import json
from typing import Any, Mapping

from pydantic import BaseModel, Field, field_validator

from modules.personalized_resource_delivery.schemas import (
    DocumentQuizAnalysis,
    FollowupGenerationContext,
    FollowupLearningRound,
    QuizAttempt,
    QuizScore,
    WrongQuestionReview,
)

from .document_quiz_generator import generate_document_quizzes_with_llm
from .goal_oriented_knowledge_explorer import explore_knowledge_points_with_llm
from .learning_document_integrator import integrate_learning_document_with_llm
from .search_enhanced_knowledge_drafter import draft_knowledge_points_with_llm


class FollowupLearningRoundPayload(BaseModel):
    learner_profile: Any
    learning_path: Any
    learning_session: Any
    quiz_attempts: list[QuizAttempt]
    quiz_analysis: DocumentQuizAnalysis | Mapping[str, Any] | str
    previous_quiz: Any
    mode: str = "A"
    round_index: int = Field(default=1, ge=1)
    allow_parallel: bool = True
    use_search: bool = True

    @field_validator("learner_profile", "learning_path", "learning_session", "previous_quiz")
    @classmethod
    def coerce_jsonish(cls, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump()
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("quiz_analysis")
    @classmethod
    def coerce_quiz_analysis(cls, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump()
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str):
            return value.strip()
        return value


def _resolve_option_value(options, option_or_index):
    if isinstance(option_or_index, int):
        if 0 <= option_or_index < len(options):
            return options[option_or_index]
        return str(option_or_index)
    if isinstance(option_or_index, str):
        if option_or_index in options:
            return option_or_index
        try:
            option_index = int(option_or_index)
        except Exception:
            return option_or_index
        if 0 <= option_index < len(options):
            return options[option_index]
    return str(option_or_index)


def _stringify_answer(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return "未作答"
    return str(value)


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "A").strip().upper()
    return "B" if normalized == "B" else "A"


def _count_quiz_distribution(previous_quiz: Mapping[str, Any]) -> dict[str, int]:
    return {
        "single_choice_count": len(previous_quiz.get("single_choice_questions", []) or []),
        "multiple_choice_count": len(previous_quiz.get("multiple_choice_questions", []) or []),
        "true_false_count": len(previous_quiz.get("true_false_questions", []) or []),
        "short_answer_count": len(previous_quiz.get("short_answer_questions", []) or []),
    }


def _build_quiz_blueprint(previous_quiz: Mapping[str, Any]) -> list[dict[str, Any]]:
    blueprint: list[dict[str, Any]] = []

    for index, question in enumerate(previous_quiz.get("single_choice_questions", []) or []):
        options = question.get("options", []) or []
        blueprint.append({
            "question_id": f"single_choice_{index}",
            "question_type": "single_choice",
            "question": question.get("question", ""),
            "options": options,
            "correct_answer": _resolve_option_value(options, question.get("correct_option")),
            "explanation": question.get("explanation") or "",
        })

    for index, question in enumerate(previous_quiz.get("multiple_choice_questions", []) or []):
        options = question.get("options", []) or []
        blueprint.append({
            "question_id": f"multiple_choice_{index}",
            "question_type": "multiple_choice",
            "question": question.get("question", ""),
            "options": options,
            "correct_answer": [_resolve_option_value(options, option) for option in question.get("correct_options", []) or []],
            "explanation": question.get("explanation") or "",
        })

    for index, question in enumerate(previous_quiz.get("true_false_questions", []) or []):
        blueprint.append({
            "question_id": f"true_false_{index}",
            "question_type": "true_false",
            "question": question.get("question", ""),
            "options": ["True", "False"],
            "correct_answer": "True" if question.get("correct_answer") else "False",
            "explanation": question.get("explanation") or "",
        })

    for index, question in enumerate(previous_quiz.get("short_answer_questions", []) or []):
        blueprint.append({
            "question_id": f"short_answer_{index}",
            "question_type": "short_answer",
            "question": question.get("question", ""),
            "options": [],
            "correct_answer": question.get("expected_answer", ""),
            "explanation": question.get("explanation") or "",
        })

    return blueprint


def _summarize_learner_profile(learner_profile: Any) -> list[str]:
    if not isinstance(learner_profile, Mapping):
        return [f"- 学习者画像：{learner_profile}"]

    cognitive_status = learner_profile.get("cognitive_status") or {}
    learning_preferences = learner_profile.get("learning_preferences") or {}
    behavioral_patterns = learner_profile.get("behavioral_patterns") or {}

    mastered_skills = cognitive_status.get("mastered_skills") or []
    in_progress_skills = cognitive_status.get("in_progress_skills") or []
    preferred_content = learning_preferences.get("content_depth") or learning_preferences.get("study_preference") or "未说明"
    preferred_pace = behavioral_patterns.get("engagement_style") or behavioral_patterns.get("attention_span") or "未说明"

    return [
        f"- 总体进度：{cognitive_status.get('overall_progress', '未知')}%",
        f"- 已掌握技能：{len(mastered_skills)} 项",
        f"- 学习中技能：{len(in_progress_skills)} 项",
        f"- 偏好的内容深度/风格：{preferred_content}",
        f"- 行为模式提示：{preferred_pace}",
    ]


def _build_generation_context(
    learner_profile: Any,
    quiz_attempts: list[QuizAttempt],
    quiz_analysis: Mapping[str, Any],
) -> dict[str, Any]:
    wrong_question_items: list[WrongQuestionReview] = []
    correct_count = sum(1 for attempt in quiz_attempts if attempt.is_correct is True)
    total_count = len(quiz_attempts)
    score_payload = quiz_analysis.get("score") or {
        "correct_count": correct_count,
        "total_count": total_count,
        "score_percentage": round((correct_count / total_count) * 100, 2) if total_count else 0.0,
    }

    for attempt in quiz_attempts:
        if attempt.is_correct is False:
            wrong_question_items.append(WrongQuestionReview(
                question_id=attempt.question_id,
                question_type=attempt.question_type,
                question=attempt.question,
                user_answer=attempt.user_answer,
                correct_answer=attempt.correct_answer,
                explanation=attempt.explanation,
            ))

    context = FollowupGenerationContext(
        previous_score=QuizScore.model_validate(score_payload),
        wrong_questions=wrong_question_items,
        weak_points=quiz_analysis.get("weak_points") or [],
        recommendations=quiz_analysis.get("recommendations") or [],
        learner_profile=learner_profile,
    )
    return context.model_dump()


def _build_followup_session(
    learning_session: Mapping[str, Any],
    generation_context: Mapping[str, Any],
    round_index: int,
) -> dict[str, Any]:
    followup_session = copy.deepcopy(dict(learning_session))
    original_title = str(followup_session.get("title") or "学习环节").strip()
    previous_score = generation_context.get("previous_score") or {}
    wrong_questions = generation_context.get("wrong_questions") or []
    weak_points = generation_context.get("weak_points") or []
    recommendations = generation_context.get("recommendations") or []

    abstract_lines = [
        "本环节是学习者在完成上一轮测验后生成的针对性补强轮次。",
        f"上一轮得分：{previous_score.get('score_percentage', 0)}%（{previous_score.get('correct_count', 0)}/{previous_score.get('total_count', 0)}）。",
        "你必须重点讲解学习者答错或仍未掌握的概念。",
    ]
    if weak_points:
        abstract_lines.append("需要重点突破的薄弱点：")
        abstract_lines.extend(f"- {point}" for point in weak_points)
    if wrong_questions:
        abstract_lines.append("需要补救的错题：")
        for item in wrong_questions:
            abstract_lines.append(f"- 题目：{item.get('question', '')}")
            abstract_lines.append(f"  学习者答案：{_stringify_answer(item.get('user_answer'))}")
            abstract_lines.append(f"  参考答案：{_stringify_answer(item.get('correct_answer'))}")
            abstract_lines.append(f"  解析：{item.get('explanation') or '暂无'}")
    if recommendations:
        abstract_lines.append("后续教学建议：")
        abstract_lines.extend(f"- {recommendation}" for recommendation in recommendations)

    followup_session["id"] = f"{followup_session.get('id', 'Session')}-Followup-{round_index}"
    followup_session["title"] = f"{original_title} · 补强轮次 {round_index}"
    followup_session["abstract"] = "\n".join(abstract_lines)
    followup_session["if_learned"] = False
    followup_session["associated_skills"] = list(followup_session.get("associated_skills", []) or [])
    return followup_session


def _build_mode_b_section_document(
    learning_session: Mapping[str, Any],
    generation_context: Mapping[str, Any],
    round_index: int,
) -> str:
    title = f"{learning_session.get('title', '学习环节')} · 补强练习 {round_index}"
    previous_score = generation_context.get("previous_score") or {}
    wrong_questions = generation_context.get("wrong_questions") or []
    weak_points = generation_context.get("weak_points") or []
    recommendations = generation_context.get("recommendations") or []
    learner_profile_summary = _summarize_learner_profile(generation_context.get("learner_profile"))

    lines = [
        f"# {title}",
        "",
        "本轮采用模式 B：不额外展开长篇新讲解，而是先给出针对性回顾，再直接进入新的测验。",
        "",
        "## 当前轮次回顾",
        "",
        f"- 上一轮得分：{previous_score.get('score_percentage', 0)}% ({previous_score.get('correct_count', 0)}/{previous_score.get('total_count', 0)})",
    ]

    if weak_points:
        lines.extend(["", "## 重点薄弱点", ""])
        lines.extend(f"- {point}" for point in weak_points)

    if wrong_questions:
        lines.extend(["", "## 错题回顾", ""])
        for item in wrong_questions:
            lines.append(f"### {item.get('question', '题目')}")
            lines.append(f"- 你的答案：{_stringify_answer(item.get('user_answer'))}")
            lines.append(f"- 标准答案：{_stringify_answer(item.get('correct_answer'))}")
            lines.append(f"- 解释：{item.get('explanation') or '暂无解释'}")
            lines.append("")

    if recommendations:
        lines.extend(["## 作答提示", ""])
        lines.extend(f"- {recommendation}" for recommendation in recommendations)

    lines.extend(["", "## 学习者画像摘要", ""])
    lines.extend(learner_profile_summary)
    return "\n".join(lines)


def _build_quiz_generation_focus(
    learning_session: Mapping[str, Any],
    generation_context: Mapping[str, Any],
    quiz_blueprint: list[dict[str, Any]],
) -> str:
    lines = [
        f"Base session title: {learning_session.get('title', '')}",
        "Generate a fresh quiz that preserves the same question-type distribution and roughly the same knowledge coverage as the quiz blueprint.",
        "Prioritize the learner's weak points and earlier mistakes first.",
    ]
    weak_points = generation_context.get("weak_points") or []
    if weak_points:
        lines.append("Weak points:")
        lines.extend(f"- {point}" for point in weak_points)

    wrong_questions = generation_context.get("wrong_questions") or []
    if wrong_questions:
        lines.append("Wrong questions to reinforce:")
        for item in wrong_questions:
            lines.append(f"- Question: {item.get('question', '')}")
            lines.append(f"  Learner answer: {_stringify_answer(item.get('user_answer'))}")
            lines.append(f"  Reference answer: {_stringify_answer(item.get('correct_answer'))}")
            lines.append(f"  Explanation: {item.get('explanation') or 'N/A'}")
    else:
        lines.append("The learner answered everything correctly in the previous round, so keep the same coverage but slightly vary the surface form and maintain challenge.")

    if quiz_blueprint:
        lines.append("Quiz blueprint coverage anchors:")
        for item in quiz_blueprint:
            lines.append(
                "- [{question_type}] {question} | answer: {answer} | explanation: {explanation}".format(
                    question_type=item.get("question_type", ""),
                    question=item.get("question", ""),
                    answer=_stringify_answer(item.get("correct_answer")),
                    explanation=item.get("explanation") or "N/A",
                )
            )

    return "\n".join(lines)


def generate_followup_learning_round_with_llm(
    llm,
    learner_profile,
    learning_path,
    learning_session,
    quiz_attempts,
    quiz_analysis,
    previous_quiz,
    *,
    mode: str = "A",
    round_index: int = 1,
    allow_parallel: bool = True,
    use_search: bool = True,
):
    payload = FollowupLearningRoundPayload.model_validate({
        "learner_profile": learner_profile,
        "learning_path": learning_path,
        "learning_session": learning_session,
        "quiz_attempts": quiz_attempts,
        "quiz_analysis": quiz_analysis,
        "previous_quiz": previous_quiz,
        "mode": mode,
        "round_index": round_index,
        "allow_parallel": allow_parallel,
        "use_search": use_search,
    })

    normalized_mode = _normalize_mode(payload.mode)
    quiz_analysis_dict = payload.quiz_analysis
    if isinstance(quiz_analysis_dict, str):
        quiz_analysis_dict = json.loads(quiz_analysis_dict)
    quiz_analysis_dict = DocumentQuizAnalysis.model_validate(quiz_analysis_dict).model_dump()

    previous_quiz_dict = payload.previous_quiz
    if not isinstance(previous_quiz_dict, Mapping):
        previous_quiz_dict = {}

    generation_context = _build_generation_context(
        payload.learner_profile,
        payload.quiz_attempts,
        quiz_analysis_dict,
    )
    quiz_blueprint = _build_quiz_blueprint(previous_quiz_dict)
    quiz_distribution = _count_quiz_distribution(previous_quiz_dict)
    generation_focus = _build_quiz_generation_focus(
        payload.learning_session if isinstance(payload.learning_session, Mapping) else {},
        generation_context,
        quiz_blueprint,
    )

    if normalized_mode == "A":
        followup_session = _build_followup_session(
            payload.learning_session if isinstance(payload.learning_session, Mapping) else {},
            generation_context,
            payload.round_index,
        )
        knowledge_points_result = explore_knowledge_points_with_llm(
            llm,
            payload.learner_profile,
            payload.learning_path,
            followup_session,
        )
        knowledge_points = knowledge_points_result.get("knowledge_points", []) if isinstance(knowledge_points_result, Mapping) else []
        knowledge_drafts = draft_knowledge_points_with_llm(
            llm,
            payload.learner_profile,
            payload.learning_path,
            followup_session,
            knowledge_points,
            allow_parallel=payload.allow_parallel,
            use_search=payload.use_search,
        )
        section_document = integrate_learning_document_with_llm(
            llm,
            payload.learner_profile,
            payload.learning_path,
            followup_session,
            knowledge_points,
            knowledge_drafts,
            output_markdown=True,
        )
        section_title = followup_session.get("title", f"Follow-up Round {payload.round_index}")
    else:
        section_document = _build_mode_b_section_document(
            payload.learning_session if isinstance(payload.learning_session, Mapping) else {},
            generation_context,
            payload.round_index,
        )
        section_title = f"{payload.learning_session.get('title', '学习环节')} · 补强练习 {payload.round_index}" if isinstance(payload.learning_session, Mapping) else f"补强练习 {payload.round_index}"

    quizzes = generate_document_quizzes_with_llm(
        llm,
        payload.learner_profile,
        section_document,
        quiz_blueprint=quiz_blueprint,
        generation_focus=generation_focus,
        **quiz_distribution,
    )

    round_payload = FollowupLearningRound(
        mode=normalized_mode,
        round_index=payload.round_index,
        section_title=section_title,
        section_document=section_document,
        quizzes=quizzes,
        generation_context=generation_context,
    )
    return round_payload.model_dump()
