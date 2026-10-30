import streamlit as st
from collections import defaultdict
import pandas as pd
import re
import time

from utils.state import get_current_session_uid

def render_dashboard():
    goal = st.session_state["goals"][st.session_state["selected_goal_id"]]

    if not goal["learner_profile"]:
        # 无画像时下面的渲染会直接访问画像字段而崩溃，必须在此中止本页渲染
        st.warning("请等待学习路径安排完成后查看仪表盘。")
        st.stop()

    st.title("学习分析")
    st.write("在此跟踪您的学习进度并查看学习洞察。")
    with st.container(border=True):
        render_learning_progress(goal)
    with st.container(border=True):
        render_skill_radar_chart(goal)
    with st.container(border=True):
        render_session_learning_timeseries(goal)
    with st.container(border=True):
        render_mastery_skills_timeseries(goal)


def render_learning_progress(goal):
    st.markdown("#### 学习进度")
    st.write("查看每个环节的学习进度。")
    learner_profile = goal["learner_profile"]
    overall_progress = learner_profile["cognitive_status"]["overall_progress"]
    st.progress(overall_progress)
    st.write(f"总体进度：{overall_progress:.2f}%")

def render_skill_radar_chart(goal):
    import plotly.graph_objects as go

    st.markdown("#### 不同技能的熟练度水平")
    # st.write("View the skill radar chart for your learning progress.")
    learner_profile = goal["learner_profile"]
    mastered_skills = learner_profile["cognitive_status"]["mastered_skills"]
    in_progress_skills = learner_profile["cognitive_status"]["in_progress_skills"]
    level_map = defaultdict(lambda: 0, {"unlearned": 0, "beginner": 1, "intermediate": 2, "advanced": 3})
    mastered_skills = [{
        "name": skill_info["name"], 
        "required_level": skill_info["proficiency_level"], 
        "current_level": skill_info["proficiency_level"]} for skill_info in mastered_skills]
    in_progress_skills = [{
        "name": skill_info["name"], 
        "required_level": skill_info["required_proficiency_level"], 
        "current_level": skill_info["current_proficiency_level"]} for skill_info in in_progress_skills]
    skills = mastered_skills + in_progress_skills
    skill_names = [skill["name"] for skill in skills]
    current_levels = [level_map[skill["current_level"]] for skill in skills]
    required_levels = [level_map[skill["required_level"]] for skill in skills]
    st.write(f"您已掌握 {len(mastered_skills)} 个技能，目前正在学习 {len(in_progress_skills)} 个技能。")

    fig = go.Figure()

    fig.add_trace(go.Scatterpolar(
        r=current_levels,
        theta=skill_names,
        fill='toself',
        name='当前熟练度',
        fillcolor='rgba(192, 90, 60, 0.15)',
        line=dict(color='#C05A3C', width=2)
    ))
    fig.add_trace(go.Scatterpolar(
        r=required_levels,
        theta=skill_names,
        fill='toself',
        name='要求熟练度',
        fillcolor='rgba(110, 103, 94, 0.10)',
        line=dict(color='#6E675E', width=2, dash='dot')
    ))

    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#2A2620', family='"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif'),
        polar=dict(
            bgcolor='rgba(0,0,0,0)',
            radialaxis=dict(
                visible=True,
                range=[0, 3],
                tickvals=[0, 1, 2, 3],
                ticktext=['未学习', '初级', '中级', '高级'],
                tickfont=dict(size=14, color='#6E675E'),
                gridcolor='#EAE3D8',
                linecolor='#EAE3D8'
            ),
            angularaxis=dict(  # Set font size for skill names (theta labels)
                tickfont=dict(size=18, color='#2A2620'),
                gridcolor='#EAE3D8',
                linecolor='#EAE3D8'
            )
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.1,
            xanchor="center",
            x=0.5,
            font=dict(size=18)
        ),
    )
    event = st.plotly_chart(fig, key=f"skill_radar_{goal['id']}", on_select="rerun")


def render_session_learning_timeseries(goal):
    st.markdown("#### 环节学习时长趋势")
    st.write("查看学习进度随时间的变化。")
    goal = st.session_state["goals"][st.session_state["selected_goal_id"]]
    session_data = {
        "学习环节": [],
        "学习时长（分钟）": [],
    }
    for session in goal["learning_path"]:
        session_data["学习环节"].append(session['id'])
        if_learned = session['if_learned']
        
        if if_learned:
            selected_gid = st.session_state["selected_goal_id"]
            match = re.search(r'\d+', session['id'])
            selected_sid = int(match.group(0)) -1
            times = st.session_state["session_learning_times"].get(f'{selected_gid}-{selected_sid}')
            if times and times.get("end_time") is not None:
                # st.markdown(times)
                time_spent = (times["end_time"] - times["start_time"]) / 60
                # st.markdown(time_spent)
            else:  
                time_spent = 0
            session_data["学习时长（分钟）"].append(time_spent)
            # st.markdown(session_data)
        else:
            session_data["学习时长（分钟）"].append(0)
    
    for sid, session in enumerate(goal["learning_path"]):
        session_uid = session["id"]
        if session_uid not in session_data["学习环节"]:
            session_data["学习环节"].append(session_uid)
            session_data["学习时长（分钟）"].append(0)

    session_data = pd.DataFrame(session_data)

    st.bar_chart(session_data, x="学习环节", y="学习时长（分钟）", stack=False, color="#C05A3C")
    

def render_mastery_skills_timeseries(goal):
    st.markdown("#### 技能掌握度趋势")
    st.write("查看学习进度随时间的变化。")
    history = st.session_state['learned_skills_history'].get(str(goal['id']), [])
    time_values = [i * 10 for i in range(len(history))]
    char_data = pd.DataFrame({
        '掌握率': history,
        '时间': time_values,
    })
    st.line_chart(char_data, x='时间', y='掌握率', color="#C05A3C")
    


render_dashboard()
