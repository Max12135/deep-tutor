import math
import streamlit as st

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


def render_skill_info(learner_profile):
    # Display Mastered Skills
    st.write("**已掌握技能：**")
    # len(learner_profile["cognitive_status"]["mastered_skills"])
    columns_spec = 2
    num_columns = math.ceil(len(learner_profile["cognitive_status"]["mastered_skills"]) / columns_spec)
    columns_list = [st.columns(spec=columns_spec) for _ in range(num_columns)]
    for idx, skill in enumerate(learner_profile["cognitive_status"]["mastered_skills"]):
        mastered_cols = columns_list[idx // columns_spec]
        with mastered_cols[idx % columns_spec]:
            st.markdown(
                f"<div class='gm-skill-card gm-skill-card--mastered'>"
                f"<strong>{skill['name']}</strong><br>"
                f"{_level_label(skill['proficiency_level'])}"
                f"</div>",
                unsafe_allow_html=True
            )

    # Skills In Progress with custom indicators
    st.write("**进行中的技能：**")
    in_progress_skills = learner_profile["cognitive_status"]["in_progress_skills"]
    num_columns = math.ceil(len(in_progress_skills) / columns_spec)
    columns_list = [st.columns(spec=columns_spec) for _ in range(num_columns)]
    for idx, skill in enumerate(in_progress_skills):
        skill_name = skill["name"]
        required_level = skill["required_proficiency_level"]
        current_level = skill["current_proficiency_level"]
        in_progress_cols = columns_list[idx // columns_spec]
        with in_progress_cols[idx % columns_spec]:
            # Render each skill in a styled box
            st.markdown(
                f"""
                <div class='gm-skill-card gm-skill-card--progress'>
                    <strong>{skill_name}</strong><br>
                    <span>要求水平：<strong>{_level_label(required_level)}</strong></span><br>
                    <span>当前水平：<strong>{_level_label(current_level)}</strong></span><br>
                </div>
                """,
                unsafe_allow_html=True
            )
