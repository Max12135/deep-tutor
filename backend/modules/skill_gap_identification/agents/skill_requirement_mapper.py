from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Dict, TypeAlias

from pydantic import BaseModel, Field, ValidationError
from base import BaseAgent
from ..prompts.skill_requirement_mapper import skill_requirement_mapper_system_prompt, skill_requirement_mapper_task_prompt
from ..schemas import SkillRequirements

logger = logging.getLogger(__name__)

JSONDict: TypeAlias = Dict[str, Any]

class Goal2SkillPayload(BaseModel):
	"""Payload for mapping a learning goal to required skills (validated)."""

	learning_goal: str = Field(...)


class SkillRequirementMapper(BaseAgent):
	"""Agent wrapper for mapping a goal to required skills."""

	name: str = "SkillRequirementMapper"

	def __init__(self, model: Any) -> None:
		super().__init__(
			model=model,
			system_prompt=skill_requirement_mapper_system_prompt,
			jsonalize_output=True,
		)
		# 更严格的 fallback prompt（不含 markdown 格式，强制直接输出 JSON）
		self._fallback_system_prompt = (
			"You are a skill mapper. Output ONLY valid JSON with a top-level key "
			'"skill_requirements" mapping to a list of objects, each with "name" '
			'(string) and "required_level" (one of "beginner", "intermediate", "advanced"). '
			"No markdown, no explanation, no code fences."
		)

	def map_goal_to_skill(self, input_dict: Mapping[str, Any], retry: bool = False) -> JSONDict:
		payload_dict = Goal2SkillPayload(**input_dict).model_dump()
		task_prompt = skill_requirement_mapper_task_prompt
		raw_output = self.invoke(payload_dict, task_prompt=task_prompt)

		# 调试日志：打印原始输出内容
		logger.debug(f"[SkillRequirementMapper] raw_output type={type(raw_output)}, value={raw_output!r}")

		# 如果返回空字典，尝试重试一次
		if not raw_output or (isinstance(raw_output, dict) and not raw_output):
			if not retry:
				logger.warning("[SkillRequirementMapper] Empty output, retrying with fallback prompt...")
				original_system = self._system_prompt
				self._system_prompt = self._fallback_system_prompt
				self._agent = self._build_agent()
				result = self.map_goal_to_skill(input_dict, retry=True)
				self._system_prompt = original_system
				self._agent = self._build_agent()
				return result
			else:
				raise ValueError(f"LLM returned empty output after retry: {raw_output!r}")

		try:
			validated = SkillRequirements.model_validate(raw_output)
		except ValidationError as e:
			logger.error(f"[SkillRequirementMapper] Validation failed: {e}, raw_output={raw_output!r}")
			raise
		return validated.model_dump(mode='json')


def map_goal_to_skills_with_llm(llm: Any, learning_goal: str) -> JSONDict:
	mapper = SkillRequirementMapper(llm)
	return mapper.map_goal_to_skill({"learning_goal": learning_goal})

