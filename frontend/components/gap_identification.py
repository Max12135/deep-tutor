import streamlit as st

from utils.request_api import create_learner_profile, identify_skill_gap
from utils.state import save_persistent_state

# 熟练度等级中文映射
LEVEL_LABELS = {
    "unlearned": "未学习",
    "beginner": "初级",
    "intermediate": "中级",
    "advanced": "高级",
}

def _level_label(level):
    """将英文等级转为中文显示"""
    return LEVEL_LABELS.get(str(level).lower(), str(level))


def render_identifying_skill_gap(goal):
    with st.spinner('正在识别技能差距...'):
        learning_goal = goal["learning_goal"]
        learner_information = st.session_state["learner_information"]
        llm_type = st.session_state["llm_type"]
        skill_gaps = identify_skill_gap(learning_goal, learner_information, llm_type)

    # 识别失败（后端不可用/LLM 报错）时不要 rerun，否则对话框会反复重试形成死循环
    if skill_gaps is None:
        st.error("技能差距识别失败，请确认后端服务已启动后重试。")
        return

    # 合法空结果：识别成功但确实没有任何技能差距。
    # 必须清掉对话框标志，否则 goal_management 会认为"还没识别"而反复重新识别。
    if not skill_gaps:
        goal["skill_gaps"] = []
        st.session_state["if_show_skill_gap_results_in_dialog"] = False
        save_persistent_state()
        st.info("未识别出任何技能差距，可直接继续下一步。")
        return

    goal["skill_gaps"] = skill_gaps
    save_persistent_state()
    st.rerun()


def render_identified_skill_gap(goal, method_name="genmentor"):
    """
    Render skill gaps in a card-style with prev/next switching.
    """
    levels = ["unlearned", "beginner", "intermediate", "advanced"]
    level_format = {l: _level_label(l) for l in levels}
    # Render all skill cards on a single page (no pagination)
    skill_gaps = goal.get("skill_gaps", [])
    total = len(skill_gaps)
    if total == 0:
        st.info("尚未识别出任何技能。")
        return

    for skill_id, skill_info in enumerate(skill_gaps):
        skill_name = skill_info.get("name", f"技能_{skill_id}")
        required_level = skill_info.get("required_level", levels[0])
        current_level = skill_info.get("current_level", levels[0])

        gap_card_class = "gm-gap-card gm-gap-card--gap" if skill_info.get("is_gap") else "gm-gap-card"

        with st.container(border=True):
            # Card header
            st.markdown(
                f"""
                <div class="{gap_card_class}">
                    <p>{skill_id+1:2d}. {skill_name}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Required level selector
            new_required_level = st.pills(
                "**要求水平**",
                options=levels,
                format_func=level_format.get,
                selection_mode="single",
                default=required_level,
                disabled=False,
                key=f"required_{skill_name}_{method_name}",
            )
            if new_required_level != required_level:
                goal["skill_gaps"][skill_id]["required_level"] = new_required_level
                if levels.index(new_required_level) > levels.index(goal["skill_gaps"][skill_id].get("current_level", levels[0])):
                    goal["skill_gaps"][skill_id]["is_gap"] = True
                else:
                    goal["skill_gaps"][skill_id]["is_gap"] = False
                save_persistent_state()
                st.rerun()

            # Current level selector
            new_current_level = st.pills(
                "**当前水平**",
                options=levels,
                format_func=level_format.get,
                selection_mode="single",
                default=current_level,
                disabled=False,
                key=f"current_{skill_name}__{method_name}",
            )
            if new_current_level != current_level:
                goal["skill_gaps"][skill_id]["current_level"] = new_current_level
                if levels.index(new_current_level) < levels.index(goal["skill_gaps"][skill_id].get("required_level", levels[0])):
                    goal["skill_gaps"][skill_id]["is_gap"] = True
                else:
                    goal["skill_gaps"][skill_id]["is_gap"] = False
                save_persistent_state()
                st.rerun()

            # Details
            with st.expander("更多分析详情"):
                if levels.index(goal["skill_gaps"][skill_id].get("current_level", levels[0])) < levels.index(goal["skill_gaps"][skill_id].get("required_level", levels[0])):
                    st.warning("当前水平低于要求水平！")
                    goal["skill_gaps"][skill_id]["is_gap"] = True
                else:
                    st.success("当前水平等于或高于要求水平")
                    goal["skill_gaps"][skill_id]["is_gap"] = False
                st.write(f"**原因**：{skill_info.get('reason', '')}")
                st.write(f"**置信度**：{skill_info.get('level_confidence', '')}")
            save_persistent_state()
            # Gap toggle
            old_gap_status = skill_info.get("is_gap", False)
            gap_status = st.toggle(
                "标记为差距",
                value=skill_info.get("is_gap", False),
                key=f"gap_{skill_name}_{method_name}",
                disabled=not skill_info.get("is_gap", False),
            )
            if gap_status != old_gap_status:
                goal["skill_gaps"][skill_id]["is_gap"] = gap_status
                if not goal["skill_gaps"][skill_id]["is_gap"]:
                    goal["skill_gaps"][skill_id]["current_level"] = goal["skill_gaps"][skill_id].get("required_level", goal["skill_gaps"][skill_id].get("current_level"))
                try:
                    save_persistent_state()
                except Exception:
                    pass
                st.rerun()

