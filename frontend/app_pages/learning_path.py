import time
import math
import html
import streamlit as st
from components.skill_info import render_skill_info
from utils.request_api import schedule_learning_path, reschedule_learning_path
from utils.state import save_persistent_state, initialize_session_state

# 确保 session_state 已初始化
initialize_session_state()

def render_learning_path():
    if not st.session_state.get("if_complete_onboarding"):
        st.switch_page("app_pages/onboarding.py")

    goal = st.session_state["goals"][st.session_state["selected_goal_id"]]
    save_persistent_state()
    if not goal["learning_goal"] or not st.session_state["learner_information"]:
        st.switch_page("app_pages/onboarding.py")
    else:
        if not goal["skill_gaps"]:
            st.switch_page("app_pages/skill_gap.py")

    # Hero 行（Reader 式）：标题居左，关键统计居右
    cognitive = goal["learner_profile"]["cognitive_status"]
    learned_sessions = sum(1 for s in goal["learning_path"] if s["if_learned"])
    total_sessions = len(goal["learning_path"])
    path_progress = int((learned_sessions / total_sessions) * 100) if total_sessions else 0
    overall_progress = int(cognitive.get("overall_progress") or 0)
    mastered_skills = len(cognitive.get("mastered_skills") or [])
    in_progress_skills = len(cognitive.get("in_progress_skills") or [])

    col_hero, col_stats = st.columns([2.6, 1])
    with col_hero:
        st.title("学习路径")
        st.write("通过以下学习环节跟踪您的学习进度。")
    with col_stats:
        st.markdown(
            f"""
<div class="mini-stat">
  <div class="mini-item"><span class="mini-value">{learned_sessions}/{total_sessions}</span><span class="mini-label">已完成环节</span></div>
  <div class="mini-item"><span class="mini-value">{overall_progress}%</span><span class="mini-label">目标掌握度</span></div>
  <div class="mini-item"><span class="mini-value">{mastered_skills}/{mastered_skills + in_progress_skills}</span><span class="mini-label">已掌握技能</span></div>
</div>
""",
            unsafe_allow_html=True,
        )

    if not goal["learning_path"]:
        st.info("正在为当前目标规划学习路径（约 20-40 秒），完成后将自动展示。")
        # 纯 CSS 骨架屏（暖灰脉冲，样式定义在 main.css）
        st.markdown(
            """
            <div class="gm-skel" style="height:110px; margin-bottom:14px;"></div>
            <div class="gm-skel" style="height:320px;"></div>
            """,
            unsafe_allow_html=True,
        )
        # session_count=0 → 由 LLM 按目标难度在 [1,10] 内自行决定环节数
        new_path = schedule_learning_path(goal["learner_profile"], session_count=0)
        if new_path:
            goal["learning_path"] = new_path
            save_persistent_state()
            st.toast("学习路径安排成功！")
            st.rerun()
        else:
            # 失败时不要保存空路径并 rerun，否则会陷入反复重新规划的循环
            st.error("学习路径规划失败，请确认后端服务已启动后重试。")
            if st.button("重试规划", type="primary"):
                st.rerun()
    else:
        render_overall_information(goal)
        render_learning_sessions(goal)
        render_reschedule_area(goal)


@st.dialog("重新安排学习路径")
def reschedule_dialog(goal):
    """点击底部按钮后弹出的小窗口，确认后才重新生成学习路径。"""
    st.warning("重新生成将替换当前学习路径，是否确认？")
    total_sessions = len(goal["learning_path"])
    default_count = min(max(total_sessions, 1), 10)
    expected_session_count = st.number_input(
        "预期学习环节数", min_value=1, max_value=10, value=default_count
    )
    col_confirm, col_cancel = st.columns(2)
    with col_confirm:
        if st.button("确认重新生成", type="primary", use_container_width=True):
            st.session_state["expected_session_count"] = expected_session_count
            st.session_state["if_rescheduling_learning_path"] = True
            try:
                save_persistent_state()
            except Exception:
                pass
            st.rerun()
    with col_cancel:
        if st.button("取消", use_container_width=True):
            st.rerun()


def render_reschedule_area(goal):
    """页面最底部的重新安排入口：普通按钮 + 确认弹窗。"""
    st.divider()
    _, col_mid, _ = st.columns([1, 2, 1])
    with col_mid:
        if st.button("重新安排学习路径", use_container_width=True, icon=":material/autorenew:"):
            reschedule_dialog(goal)

    if st.session_state.get("if_rescheduling_learning_path"):
        with st.spinner("正在重新安排学习路径..."):
            new_path = reschedule_learning_path(
                goal["learning_path"],
                goal["learner_profile"],
                st.session_state.get("expected_session_count", len(goal["learning_path"])),
            )
            st.session_state["if_rescheduling_learning_path"] = False
            # 失败（返回 None）时保留原学习路径，避免被后续渲染当成空路径重新生成
            if new_path:
                goal["learning_path"] = new_path
                try:
                    save_persistent_state()
                except Exception:
                    pass
                st.toast("学习路径重新安排成功！")
            else:
                st.toast("重新安排失败，已保留原学习路径。")
            st.rerun()


def render_overall_information(goal):
    with st.container(border=True):
        st.write("####  当前目标")
        st.text_area("进行中的目标", value=goal["learning_goal"], disabled=True, help="请在目标管理部分修改。")
        learned_sessions = sum(1 for s in goal["learning_path"] if s["if_learned"])
        total_sessions = len(goal["learning_path"])
        progress = int((learned_sessions / total_sessions) * 100) if total_sessions else 0
        st.progress(progress)

        if learned_sessions == total_sessions and total_sessions > 0:
            st.success("恭喜！所有学习环节已全部完成！")
        else:
            st.info("继续加油！您正在取得很大的进步。")
        st.write("**技能详情**")
        render_skill_info(goal["learner_profile"])

def render_learning_sessions(goal):
    st.write("####  学习环节")
    save_persistent_state()
    columns_spec = 2
    num_columns = math.ceil(len(goal["learning_path"]) / columns_spec)  
    columns_list = [st.columns(columns_spec, gap="large") for _ in range(num_columns)]
    for sid, session in enumerate(goal["learning_path"]):
        session_column = columns_list[sid // columns_spec]
        with session_column[sid % columns_spec]:
            with st.container(border=True):
                title_class = "gm-session-title gm-session-title--done" if session["if_learned"] else "gm-session-title"
                chip = ('<span class="gm-chip gm-chip--done">已完成</span>'
                        if session["if_learned"]
                        else '<span class="gm-chip gm-chip--todo">待学习</span>')
                st.markdown(
                    f"<div style='display:flex; align-items:center; justify-content:space-between; gap:8px;'>"
                    f"<span class='{title_class}'>{sid+1}: {session['title']}</span>{chip}</div>",
                    unsafe_allow_html=True,
                )

                st.markdown(
                    f"<div class='gm-session-desc'>{html.escape(str(session['abstract']))}</div>",
                    unsafe_allow_html=True,
                )
                outcomes = session["desired_outcome_when_completed"]
                if outcomes:
                    outcome_chips = "".join(
                        f"<span class='gm-outcome'>{html.escape(str(o['name']))}"
                        f"<span class='gm-outcome-level'>{html.escape(str(o['level']))}</span></span>"
                        for o in outcomes
                    )
                    st.markdown(
                        f"<p class='gm-session-outcomes-label'>关联技能及期望熟练度</p>"
                        f"<div class='gm-outcome-list'>{outcome_chips}</div>",
                        unsafe_allow_html=True,
                    )

                # 开始学习按钮独占一行，避免在窄列里被挤成竖排
                start_key = f"start_{session['id']}_{session['if_learned']}"
                if not session["if_learned"]:
                    if st.button("开始学习", key=start_key, use_container_width=True, type="secondary", icon=":material/local_library:"):
                        st.session_state["selected_session_id"] = sid
                        st.session_state["selected_point_id"] = 0
                        st.session_state["selected_page"] = "Knowledge Document"
                        save_persistent_state()
                        st.switch_page("app_pages/knowledge_document.py")
                else:
                    if st.button("已完成", key=start_key, use_container_width=True, type="secondary", icon=":material/done_outline:"):
                        st.session_state["selected_session_id"] = sid
                        st.session_state["selected_point_id"] = 0
                        st.session_state["selected_page"] = "Knowledge Document"
                        save_persistent_state()
                        st.switch_page("app_pages/knowledge_document.py")


render_learning_path()