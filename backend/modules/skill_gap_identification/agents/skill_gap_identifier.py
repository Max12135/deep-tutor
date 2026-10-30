from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Dict, Optional, Tuple, TypeAlias
from pydantic import BaseModel, Field, ValidationError
from base import BaseAgent
from ..prompts.skill_gap_identifier import skill_gap_identifier_system_prompt, skill_gap_identifier_task_prompt
from ..schemas import SkillRequirements, SkillGaps
from .skill_requirement_mapper import SkillRequirementMapper

logger = logging.getLogger(__name__)

JSONDict: TypeAlias = Dict[str, Any]


class SkillGapPayload(BaseModel):
    """Payload for identifying skill gaps (validated)."""

    learning_goal: str = Field(...)
    learner_information: str = Field(...)
    skill_requirements: Dict[str, Any] = Field(...)


class SkillGapIdentifier(BaseAgent):
    """Agent wrapper for skill requirement discovery and gap identification."""

    name: str = "SkillGapIdentifier"

    def __init__(self, model: Any) -> None:
        super().__init__(
            model=model,
            system_prompt=skill_gap_identifier_system_prompt,
            jsonalize_output=True,
        )
        self._fallback_system_prompt = (
            "You are a skill gap analyzer. Output ONLY valid JSON with a top-level key "
            '"skill_gaps" mapping to a list of objects with fields: '
            '"name" (string), "is_gap" (bool), "required_level" '
            '("beginner"|"intermediate"|"advanced"), '
            '"current_level" ("unlearned"|"beginner"|"intermediate"|"advanced"), '
            '"reason" (string, max 20 words), '
            '"level_confidence" ("low"|"medium"|"high"). '
            "No markdown, no explanation."
        )

    def identify_skill_gap(
        self,
        input_dict: Mapping[str, Any],
        retry: bool = False,
    ) -> JSONDict:
        """Identify knowledge gaps using learner information and expected skills."""
        payload_dict = SkillGapPayload(**input_dict).model_dump()
        task_prompt = skill_gap_identifier_task_prompt
        raw_output = self.invoke(payload_dict, task_prompt=task_prompt)

        logger.debug(f"[SkillGapIdentifier] raw_output type={type(raw_output)}, value={raw_output!r}")

        if not raw_output or (isinstance(raw_output, dict) and not raw_output):
            if not retry:
                logger.warning("[SkillGapIdentifier] Empty output, retrying with fallback prompt...")
                original_system = self._system_prompt
                self._system_prompt = self._fallback_system_prompt
                self._agent = self._build_agent()
                result = self.identify_skill_gap(input_dict, retry=True)
                self._system_prompt = original_system
                self._agent = self._build_agent()
                return result
            else:
                raise ValueError(f"LLM returned empty output after retry: {raw_output!r}")

        try:
            validated = SkillGaps.model_validate(raw_output)
        except ValidationError as e:
            logger.error(f"[SkillGapIdentifier] Validation failed: {e}, raw_output={raw_output!r}")
            raise
        return validated.model_dump(mode='json')


def identify_skill_gap_with_llm(
    llm: Any,
    learning_goal: str,
    learner_information: str,
    skill_requirements: Optional[Dict[str, Any]] = None,
) -> Tuple[JSONDict, JSONDict]:
    """Identify skill gaps and return both the gaps and the skill requirements used."""

    # Compute requirements if not provided
    if not skill_requirements:
        mapper = SkillRequirementMapper(llm)
        effective_requirements = mapper.map_goal_to_skill({"learning_goal": learning_goal})
    else:
        effective_requirements = skill_requirements

    skill_gap_identifier = SkillGapIdentifier(llm)
    skill_gaps = skill_gap_identifier.identify_skill_gap(
        {
            "learning_goal": learning_goal,
            "learner_information": learner_information,
            "skill_requirements": effective_requirements,
        },
    )
    return skill_gaps, effective_requirements

if __name__ == "__main__":
    # python -m modules.skill_gap_identification.agents.skill_gap_identifier
    from base.llm_factory import LLMFactory

    llm = LLMFactory.create(model="deepseek-chat", model_provider="deepseek")

    learning_goal = "Become proficient in data science."
    learner_information = "I have a background in statistics but limited programming experience."

    skill_gaps, skill_requirements = identify_skill_gap_with_llm(
        llm,
        learning_goal,
        learner_information,
    )

    print("Identified Skill Gap:", skill_gaps)
    print("Skill Requirements Used:", skill_requirements)