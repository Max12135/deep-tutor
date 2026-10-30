import math
import streamlit as st
from utils.request_api import create_learner_profile, update_learner_profile
from components.skill_info import render_skill_info
from utils.pdf import extract_text_from_pdf
from streamlit_extras.tags import tagger_component 
from utils.state import save_persistent_state


def render_learner_profile():
    # Title and introduction
    goal = st.session_state["goals"][st.session_state["selected_goal_id"]]

    st.title("学习者资料")
    st.write("学习者背景、目标、进度、偏好和行为模式的概览。")
    if not goal["learner_profile"]:
        with st.spinner('正在识别技能差距...'):
            st.info("请完成引导流程以查看学习者资料。")
    else:
        try:
            render_learner_profile_info(goal)
        except Exception as e:
            st.error("渲染学习者资料时发生错误。")
            # 兜底重建：失败时绝不写盘，否则会把 None 抹进画像，
            # 导致主入口每次刷新访问画像字段时报 TypeError，整个应用从此打不开。
            if st.button("重新生成学习者资料", type="primary"):
                with st.spinner("正在重新准备您的资料..."):
                    new_profile = create_learner_profile(
                        goal["learning_goal"],
                        st.session_state["learner_information"],
                        goal["skill_gaps"],
                        st.session_state["llm_type"],
                    )
                if new_profile:
                    goal["learner_profile"] = new_profile
                    try:
                        save_persistent_state()
                    except Exception:
                        pass
                    st.rerun()
                else:
                    st.error("重新生成失败，请确认后端服务已启动后重试。")
            return

def render_learner_profile_info(goal):
    learner_profile = goal["learner_profile"]
    with st.container(border=True):
        # 学习者信息
        st.markdown("####  学习者信息")
        st.markdown(f"<div class='gm-section'>{learner_profile['learner_information']}</div>", unsafe_allow_html=True)

        # 学习目标
        st.markdown("####  学习目标")
        st.markdown(f"<div class='gm-section'>{learner_profile['learning_goal']}</div>", unsafe_allow_html=True)

    with st.container(border=True):
        render_cognitive_status(goal)
    with st.container(border=True):
        render_learning_preferences(goal)
    with st.container(border=True):
        render_behavioral_patterns(goal)

    render_additional_info_form(goal)


def render_cognitive_status(goal):
    learner_profile = goal["learner_profile"]
    # 认知状态
    st.markdown("####  认知状态")
    st.write("**总体进度：**")
    st.progress(learner_profile["cognitive_status"]["overall_progress"])
    st.markdown(f"**{learner_profile['cognitive_status']['overall_progress']}% 已完成**")
    render_skill_info(learner_profile)

def render_learning_preferences(goal):
    learner_profile = goal["learner_profile"]
    st.markdown("####  学习偏好")
    st.write(f"**内容风格：** {learner_profile['learning_preferences']['content_style']}")
    st.write(f"**偏好活动类型：** {learner_profile['learning_preferences']['activity_type']}")
    st.write(f"**备注：**")
    st.info(learner_profile['learning_preferences'].get('additional_notes') or "暂无")

def render_behavioral_patterns(goal):
    learner_profile = goal["learner_profile"]
    st.markdown("####  行为模式")
    st.write(f"**系统使用频率：**")
    st.info(learner_profile['behavioral_patterns']['system_usage_frequency'])
    st.write(f"**学习时长和参与度：**")
    st.info(learner_profile['behavioral_patterns']['session_duration_engagement'])
    st.write(f"**激励触发因素：**")
    st.info(learner_profile['behavioral_patterns'].get('motivational_triggers') or "暂无")
    st.write(f"**备注：**")
    st.info(learner_profile['behavioral_patterns'].get('additional_notes') or "暂无")


def render_additional_info_form(goal):
    with st.form(key="additional_info_form"):
        st.markdown("#### 您的反馈")
        st.info("通过以下反馈帮助我们改善您的学习体验。")
        st.write("您对当前资料的认同程度如何？")
        agreement_star = st.feedback("stars", key="agreement_star")
        st.write("您有什么建议或修正吗？")
        suggestions = st.text_area("请在此输入您的建议。", label_visibility="collapsed")
        st.write("您有什么额外信息要添加吗？")
        additional_info = st.text_area("请在此输入任何额外信息或反馈。", label_visibility="collapsed")
        pdf_file = st.file_uploader("上传包含额外信息的 PDF（如简历）", type="pdf")
        if pdf_file is not None:
            with st.spinner("正在提取 PDF 文本..."):
                additional_info_pdf = extract_text_from_pdf(pdf_file)
                st.toast("PDF 上传成功！")
        else:
            additional_info_pdf = ""
        # 不使用 on_click+kwargs：回调在下一轮 rerun 开始时执行，携带的是"上一次渲染"的
        # 旧值，首次提交会把空反馈发给后端。改为在提交分支内读取本轮最新控件值。
        submit_button = st.form_submit_button("更新资料", type="primary")
        if submit_button:
            payload = {
                "agreement_star": agreement_star,
                "suggestions": suggestions,
                "additional_info": additional_info + additional_info_pdf,
            }
            st.session_state["additional_info"] = payload
            update_learner_profile_with_additional_info(goal, payload)


def update_learner_profile_with_additional_info(goal, additional_info):
    new_learner_profile = update_learner_profile(goal["learner_profile"], additional_info)
    if new_learner_profile is not None:
        goal["learner_profile"] = new_learner_profile
        try:
            save_persistent_state()
        except Exception:
            pass
        st.toast("您的资料已成功更新！")
    else:
        st.toast("更新资料失败，请重试。")


render_learner_profile()