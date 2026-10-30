import streamlit as st

from components.goal_refinement import render_goal_refinement
from utils.request_api import create_learner_profile, identify_skill_gap
from components.gap_identification import render_identified_skill_gap, render_identifying_skill_gap
from utils.state import add_new_goal, change_selected_goal_id, index_goal_by_id, reset_to_add_goal, save_persistent_state
from components.skill_info import render_skill_info


@st.dialog("编辑目标")
def edit_goal_dialog(goal):
    """以弹窗形式编辑目标，替代原先内联 text_area + 嵌套保存按钮的反模式。"""
    edited_goal = st.text_area("目标内容", value=goal["learning_goal"])
    if st.button("保存", key=f"save_{goal['id']}", type="primary", use_container_width=True):
        goal["learning_goal"] = edited_goal
        try:
            save_persistent_state()
        except Exception:
            pass
        st.toast("目标更新成功！")
        st.rerun()


def render_goal_management():
    st.title("目标管理")
    st.write("管理您的学习目标：添加新目标、编辑或删除现有目标。")

    render_add_new_goal()
    st.divider()
    render_existing_goals()

def render_add_new_goal():
    if "if_refining_learning_goal"not in st.session_state:
        st.session_state["if_refining_learning_goal"] = False
        try:
            save_persistent_state()
        except Exception:
            pass
    if "if_show_skill_gap_results_in_dialog"not in st.session_state:
        st.session_state["if_show_skill_gap_results_in_dialog"] = False
        try:
            save_persistent_state()
        except Exception:
            pass

    to_add_goal = st.session_state["to_add_goal"]
    st.subheader("添加新目标")
    new_learning_goal = st.text_area("输入您的新目标：", to_add_goal["learning_goal"], key="new_learning_goal")
    to_add_goal["learning_goal"] = new_learning_goal

    refine_col, clear_col, hint_col, add_col = st.columns([1, 1, 2.6, 1.4])

    render_goal_refinement(to_add_goal, refine_col, hint_col)
    if clear_col.button("清空", key="clear_goal"):
        reset_to_add_goal()
        try:
            save_persistent_state()
        except Exception:
            pass
        st.rerun()

    if add_col.button("添加目标", type="primary", icon=":material/add:", use_container_width=True):
        if new_learning_goal:
            render_skill_gap_dialog()
        else:
            hint_col.warning("请在添加之前输入一个目标。")

    if st.session_state["if_show_skill_gap_results_in_dialog"]:
        render_skill_gap_dialog()



def render_existing_goals():
    st.subheader("现有目标")
    goals = st.session_state["goals"]
    non_deleted_goals = [goal for goal in goals if not goal["is_deleted"]]

    for goal_id, goal in enumerate(non_deleted_goals):
        with st.container():
            col_left, col_right = st.columns([3, 1])
            col_left.write(f"#### 目标 {goal_id + 1}")
            
            # 检查当前目标是否为活动目标
            is_active = st.session_state.get("selected_goal_id") == goal["id"]
            
            if is_active:
                col_right.button("当前活动目标", type="primary", key=f"active_{goal['id']}", use_container_width=True)
            else:
                if col_right.button("设为活动目标", key=f"set_{goal['id']}", help="将此目标设为您当前的学习目标。"):
                    st.session_state.selected_goal_id = goal["id"]
                    try:
                        save_persistent_state()
                    except Exception:
                        pass
                    change_selected_goal_id(goal["id"])
                    try:
                        save_persistent_state()
                    except Exception:
                        pass
                    st.rerun()
            
            st.info(f"{goal['learning_goal']}")
            st.write(f"**总体进度：**")
            learner_profile = goal["learner_profile"]
            overall_progress = learner_profile["cognitive_status"]["overall_progress"]
            progress = st.slider("进度", min_value=0, max_value=100, value=overall_progress, key=f"progress_{goal['id']}", disabled=True)
            unlearned_skill = len(goal['learner_profile']['cognitive_status']['in_progress_skills'])
            learned_skill = len(goal['learner_profile']['cognitive_status']['mastered_skills'])
            all_skill = learned_skill + unlearned_skill
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                st.metric(label="技能总数", value=all_skill, delta_color="off")
            with col2:
                st.metric(label="已掌握技能数", value=learned_skill, delta_color="off")
            with col3:
                st.metric(label="进行中技能数", value=unlearned_skill, delta_color="off")
            with st.expander("技能详情"):
                render_skill_info(goal["learner_profile"])
            
            col1, col2 = st.columns([7, 1])
            with col1:
                if st.button("编辑", key=f"edit_{goal['id']}"):
                    edit_goal_dialog(goal)
            with col2:
                if st.button("删除", key=f"delete_{goal['id']}"):
                    goal_index = index_goal_by_id(goal["id"])
                    was_active = st.session_state.get("selected_goal_id") == goal["id"]
                    st.session_state.goals[goal_index]["is_deleted"] = True
                    # 若删除的是当前活动目标，必须切走，否则后续页面会继续把已删目标当活动目标渲染
                    if was_active:
                        remaining = [g for g in st.session_state.goals if not g["is_deleted"]]
                        if remaining:
                            change_selected_goal_id(remaining[0]["id"])
                        else:
                            # 已无任何目标 → 退回引导页重新添加
                            st.session_state["if_complete_onboarding"] = False
                            st.session_state["selected_page"] = "Onboarding"
                    try:
                        save_persistent_state()
                    except Exception:
                        pass
                    st.success("目标删除成功！")
                    st.rerun()
        
        if goal_id < len(non_deleted_goals) - 1:
            st.divider()

            
            


@st.dialog("技能差距", width="large")
def render_skill_gap_dialog():
    to_add_goal = st.session_state["to_add_goal"]

    # 安全检查：确保 skill_gaps 不为 None
    if to_add_goal.get("skill_gaps") is None:
        to_add_goal["skill_gaps"] = []

    st.write("查看并确认您的技能差距。")
    num_skills = len(to_add_goal["skill_gaps"])
    num_gaps = sum(1 for skill in to_add_goal["skill_gaps"] if skill["is_gap"])
    st.info(f"共识别出 {num_skills} 个技能，其中 {num_gaps} 个存在技能差距。")
    if not to_add_goal["skill_gaps"]:
        st.session_state["if_show_skill_gap_results_in_dialog"] = True
        try:
            save_persistent_state()
        except Exception:
            pass
        render_identifying_skill_gap(to_add_goal)
    else:
        st.session_state["if_show_skill_gap_results_in_dialog"] = False
        try:
            save_persistent_state()
        except Exception:
            pass
        render_identified_skill_gap(to_add_goal)
        if_schedule_learning_path_ready = to_add_goal["skill_gaps"]
        if st.button("安排学习路径", type="primary", disabled=not if_schedule_learning_path_ready):
            if to_add_goal["skill_gaps"] and not to_add_goal["learner_profile"]:
                with st.spinner('正在创建您的个人资料...'):
                    learner_profile = create_learner_profile(to_add_goal["learning_goal"], st.session_state["learner_information"], to_add_goal["skill_gaps"])
                    if learner_profile is None:
                        st.rerun()
                    to_add_goal["learner_profile"] = learner_profile
                    st.toast("您的个人资料已创建！")
            new_goal_id = add_new_goal(**to_add_goal)
            st.session_state["selected_goal_id"] = new_goal_id
            try:
                save_persistent_state()
            except Exception:
                pass
            st.session_state["if_complete_onboarding"] = True
            try:
                save_persistent_state()
            except Exception:
                pass
            st.session_state["selected_page"] = "Learning Path"
            try:
                save_persistent_state()
            except Exception:
                pass
            st.switch_page("app_pages/learning_path.py")



render_goal_management()