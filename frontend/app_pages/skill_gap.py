import time
import json
import httpx
import streamlit as st

from utils.state import initialize_session_state
from components.topbar import render_topbar

# 确保 session_state 已初始化
initialize_session_state()
from config import backend_endpoint, use_mock_data
from components.gap_identification import render_identifying_skill_gap, render_identified_skill_gap
from utils.state import add_new_goal, reset_to_add_goal, save_persistent_state
from utils.request_api import identify_skill_gap, create_learner_profile


def render_skill_gap():
    goal = st.session_state["to_add_goal"]
    if not goal["learning_goal"] or not st.session_state["learner_information"]:
        st.switch_page("app_pages/onboarding.py")

    st.title("技能差距")
    st.write("查看并确认您的技能差距。")

    skill_gaps = goal.get("skill_gaps", [])
    if not skill_gaps:
        render_identifying_skill_gap(goal)
    else:
        num_skills = len(skill_gaps)
        num_gaps = sum(1 for skill in skill_gaps if skill.get("is_gap"))
        st.info(f"共识别出 {num_skills} 个技能，其中 {num_gaps} 个存在技能差距。")
        render_identified_skill_gap(goal)

        if_schedule_learning_path_ready = skill_gaps
        if st.button("安排学习路径", type="primary", disabled=not if_schedule_learning_path_ready):
            if skill_gaps and not goal.get("learner_profile"):
                with st.spinner('正在创建您的个人资料...'):
                    learner_profile = create_learner_profile(goal["learning_goal"], st.session_state["learner_information"], skill_gaps)
                    if learner_profile is None:
                        st.rerun()
                    goal["learner_profile"] = learner_profile
                    st.toast("您的个人资料已创建！")
            new_goal_id = add_new_goal(**goal)
            st.session_state["selected_goal_id"] = new_goal_id
            st.session_state["if_complete_onboarding"] = True
            st.session_state["selected_page"] = "Learning Path"
            save_persistent_state()
            st.switch_page("app_pages/learning_path.py")

render_skill_gap()