import streamlit as st
from utils.request_api import chat_with_tutor
from utils.state import index_goal_by_id


@st.dialog("AI 学习助手")
def ask_autor_chatbot():
    instruction = "您好！我是您的 AI 学习助手，了解你的学习目标和当前进度。有什么问题尽管问我。"
    # messages.chat_message("user").write(prompt)
    st.info(instruction)

    if index_goal_by_id(st.session_state["selected_goal_id"]) == None:
        goal = st.session_state["to_add_goal"]
    else:
        goal = st.session_state["goals"][st.session_state["selected_goal_id"]]
    learner_profile = goal["learner_profile"]

    messages = st.container(height=300)
    # 先回放历史：对话记录一直存在 session_state 里也发给了后端，但此前从不渲染，
    # 导致每次 rerun 后界面上只剩最后一轮问答。这里把已存的多轮对话原样重画出来。
    for msg in st.session_state["tutor_messages"]:
        role = msg.get("role")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.chat_message(role).write(content)

    if prompt := st.chat_input("输入你的问题…"):
        # 本轮提交：历史里还没有这条，单独画一次，避免与回放重复
        messages.chat_message("user").write(prompt)
        st.session_state["tutor_messages"].append({"role": "user", "content": prompt})
        response = chat_with_tutor(
            st.session_state["tutor_messages"][-20:],
            learner_profile,
            st.session_state["llm_type"])
        if response:
            messages.chat_message("assistant").write(response)
            st.session_state["tutor_messages"].append({"role": "assistant", "content": response})
        else:
            messages.chat_message("assistant").error("导师暂时无法回复，请确认后端服务已启动后重试。")

def click_chatbot_func():
    ask_autor_chatbot()


def render_chatbot():
    """在调用处（侧边栏）渲染"询问导师"入口按钮。

    原先通过 streamlit-float 悬浮在右下角，但与新版 Streamlit 兼容性差、
    表现为卡住的黑块，改为侧边栏普通按钮。
    """
    if st.button("AI 学习助手", type="secondary", key="chatbot", icon=":material/school:", use_container_width=True, on_click=click_chatbot_func):
        st.session_state.show_chatbot = True