from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, Field, field_validator

from base import BaseAgent
from modules.personalized_resource_delivery.prompts.document_quiz_analyzer import (
    document_quiz_analyzer_system_prompt,
    document_quiz_analyzer_task_prompt,
)
from modules.personalized_resource_delivery.schemas import DocumentQuizAnalysis, QuizAttempt


class DocumentQuizAnalysisPayload(BaseModel):
    learner_profile: Any
    quiz_attempts: list[QuizAttempt]
    session_information: Any = Field(default_factory=dict)

    @field_validator("learner_profile", "session_information")
    @classmethod
    def coerce_jsonish(cls, v: Any) -> Any:
        if isinstance(v, BaseModel):
            return v.model_dump()
        if isinstance(v, Mapping):
            return dict(v)
        if isinstance(v, str):
            return v.strip()
        return v


class DocumentQuizAnalyzer(BaseAgent):
    name: str = "DocumentQuizAnalyzer"

    def __init__(self, model: Any):
        super().__init__(model=model, system_prompt=document_quiz_analyzer_system_prompt, jsonalize_output=True)

    def analyze(self, payload: DocumentQuizAnalysisPayload | Mapping[str, Any] | str):
        if not isinstance(payload, DocumentQuizAnalysisPayload):
            payload = DocumentQuizAnalysisPayload.model_validate(payload)
        raw_output = self.invoke(payload.model_dump(), task_prompt=document_quiz_analyzer_task_prompt)
        validated_output = DocumentQuizAnalysis.model_validate(raw_output)
        return validated_output.model_dump()


def analyze_document_quiz_with_llm(
    llm,
    learner_profile,
    quiz_attempts,
    session_information=None,
):
    payload = {
        "learner_profile": learner_profile,
        "quiz_attempts": quiz_attempts,
        "session_information": session_information or {},
    }
    analyzer = DocumentQuizAnalyzer(llm)
    return analyzer.analyze(payload)
