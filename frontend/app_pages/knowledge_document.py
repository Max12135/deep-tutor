import json
import hashlib
import math
import time
import copy
import re
from pathlib import Path
import streamlit as st
from components.time_tracking import track_session_learning_start_time
from components.knowledge_graph import render_knowledge_graph, create_simple_linear_graph
from utils.request_api import (
    draft_knowledge_points,
    explore_knowledge_points,
    generate_document_quizzes,
    integrate_learning_document,
    update_learner_profile,
    generate_learning_image,
    generate_knowledge_graph,
    generate_knowledge_point_image,
    generate_session_images,
    analyze_document_quiz,
    generate_followup_learning_round,
)
from utils.format import prepare_markdown_document
from utils.state import get_current_session_uid, save_persistent_state, initialize_session_state
from config import use_mock_data, use_search


try:
    _css_path = Path(__file__).resolve().parent.parent / "assets" / "css" / "main.css"
    st.markdown('<style>' + _css_path.read_text(encoding='utf-8') + '</style>', unsafe_allow_html=True)
except Exception as _css_err:
    st.warning(f"自定义样式加载失败（不影响功能）：{_css_err}")

# 初始化 session state
initialize_session_state()


@st.cache_data(show_spinner=False, ttl=86400)
def _fetch_remote_image(url: str):
    """下载外链图片字节（带 Referer 伪装同源，绕过防盗链）。失败返回 None。

    结果按 url 缓存 24h；失败也缓存，避免反复卡顿。
    """
    try:
        import httpx
        from urllib.parse import urlparse

        parsed = urlparse(url)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": f"{parsed.scheme}://{parsed.netloc}/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        with httpx.stream("GET", url, headers=headers, timeout=8, follow_redirects=True) as resp:
            if resp.status_code == 200:
                data = b"".join(resp.iter_bytes())
                if data:
                    return data
    except Exception:
        return None
    return None


def _image_source(url):
    """返回可直接喂给 st.image 的对象：外链优先下载为字节（防防盗链裂图），
    失败则回退为原始直链（保持原有行为）。"""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return url
    data = _fetch_remote_image(url)
    return data if data else url


def render_learning_content():
    if 'if_render_qizzes'not in st.session_state:
        st.session_state['if_render_qizzes'] = False
        try:
            save_persistent_state()
        except Exception:
            pass

    goal = st.session_state["goals"][st.session_state["selected_goal_id"]]
    if not goal["learning_path"]:
        st.error("学习路径正在安排中，请稍后再访问此页面。")
        return

    render_session_details(goal)
    session_uid = get_current_session_uid()
    session_id = st.session_state["selected_session_id"]
    selected_gid = st.session_state["selected_goal_id"]
    is_document_available = st.session_state["document_caches"].get(session_uid, False)
    if not is_document_available and not st.session_state["if_updating_learner_profile"]:
        learning_content = render_content_preparation(goal)
        if learning_content is None:
            st.error("准备知识内容失败。")
            return
    else:
        track_session_learning_start_time()
        learning_content = st.session_state["document_caches"].get(session_uid, "")

        # 获取当前学习会话
        learning_session = goal["learning_path"][session_id]

        # 检查是否需要自动生成知识点配图
        # 只从按 session_uid 键控的文档缓存取，避免跨目标/环节读到上一个环节的知识点
        knowledge_points = (learning_content.get("knowledge_points") or []) if isinstance(learning_content, dict) else []
        _ensure_kp_images_auto_generated(session_uid, knowledge_points, learning_session)

        # 阅读主线（文档分页）与辅助内容（图谱/配图）分 Tab 组织，保持阅读动线聚焦
        tab_doc, tab_graph, tab_media = st.tabs(["学习文档", "知识图谱", "配图库"])
        with tab_doc:
            render_document_content_by_section(learning_content)
        with tab_graph:
            render_knowledge_graph_section(goal, learning_session)
        with tab_media:
            render_multimodal_image_generation_section(goal, learning_session, knowledge_points)

        if st.session_state['if_render_qizzes']:
            active_round = get_active_round_state(learning_content)
            session_info_for_quiz = goal["learning_path"][st.session_state["selected_session_id"]]

            if active_round is learning_content:
                # 基础轮：本环节测验 + 完成环节/反馈
                st.subheader("知识测验")
                render_questions(
                    goal, learning_content, learning_content.get("quizzes", {}), session_info_for_quiz,
                    round_key="session_round_0", round_label="Session Quiz",
                )
                render_continue_learning_controls(goal, learning_content, learning_content, session_info_for_quiz, learning_content.get("quizzes", {}))

                st.divider()
                selected_sid = st.session_state["selected_session_id"]
                complete_button_status = True if goal["learning_path"][st.session_state["selected_session_id"]]["if_learned"] else False
                if st.button("重新生成", icon=":material/refresh:"):
                    st.session_state["document_caches"].pop(session_uid)
                    try:
                        save_persistent_state()
                    except Exception:
                        pass
                    _bp = goal['learner_profile']['behavioral_patterns']
                    _bp['additional_notes'] = (_bp.get('additional_notes') or "") + f"我重新生成了第 {selected_sid} 个环节的内容。\n"
                    st.rerun()
                if st.button("完成环节",
                            key="complete-session", type="primary", icon=":material/task_alt:",
                            use_container_width=True, disabled=complete_button_status or st.session_state["if_updating_learner_profile"]):
                    trigger_session_completion(goal)

                st.divider()
                # 从 goal 获取当前 session_info（render_session_details 里定义的 session_info 在此处不可见）
                session_info_for_feedback = goal["learning_path"][st.session_state["selected_session_id"]]
                with st.expander("填写使用反馈（可选）", expanded=False):
                    render_content_feedback_form(goal, session_info=session_info_for_feedback)
                render_motivataional_triggers()
            else:
                # 补强轮：展示生成依据 + 本轮测验 + 继续学习控件
                round_index = active_round.get("round_index", 1)
                mode_label = "模式 A" if active_round.get("mode", "A") == "A" else "模式 B"
                with st.container(border=True):
                    st.caption(f"{mode_label} · {active_round.get('section_title', f'补强轮次 {round_index}')}")
                    render_followup_generation_context(active_round)
                st.subheader(f"补强测验 {round_index}")
                render_questions(
                    goal, active_round, active_round.get("quizzes", {}), session_info_for_quiz,
                    round_key=f"followup_round_{round_index}", round_label=f"Follow-up Quiz {round_index}",
                )
                render_continue_learning_controls(goal, learning_content, active_round, session_info_for_quiz, active_round.get("quizzes", {}))


def render_motivataional_triggers():
    curr_time = time.time()
    session_uid = get_current_session_uid()
    session_learning_times = st.session_state["session_learning_times"][session_uid]
    last_session_trigger_time = session_learning_times["trigger_time_list"][-1]
    last_session_trigger_time_index = len(session_learning_times["trigger_time_list"])
    trigger_interval = 60 * 3
    if curr_time - last_session_trigger_time > trigger_interval:
        if last_session_trigger_time_index % 2 == 0:
            st.toast("注意补水，保持良好坐姿。")
        else:
            st.toast("继续保持！您做得很好！")
        session_learning_times["trigger_time_list"].append(curr_time)

def trigger_session_completion(goal):
    """标记"正在完成环节"，rerun 后统一走画像更新流程。"""
    session_uid = get_current_session_uid()
    st.session_state["if_updating_learner_profile"] = True
    st.session_state["current_page"][session_uid] = 0
    try:
        save_persistent_state()
    except Exception:
        pass
    st.rerun()


def render_session_details(goal):
    selected_sid = st.session_state["selected_session_id"]
    session_uid = get_current_session_uid()
    session_info = goal["learning_path"][selected_sid]

    col1, col2, col3, col4 = st.columns([1, 2, 1, 1])
    with col1:
        if st.button("返回", icon=":material/arrow_back:", key="back-learning-center"):
            st.session_state["selected_page"] = "Learning Path"
            st.session_state["current_page"][session_uid] = 0

            st.switch_page("app_pages/learning_path.py")
            try:
                save_persistent_state()
            except Exception:
                pass

    with col3:
        if st.button("重新生成", icon=":material/refresh:", key="regenerate-content-top"):
            st.session_state["document_caches"].pop(session_uid)
            try:
                save_persistent_state()
            except Exception:
                pass
            _bp = goal['learner_profile']['behavioral_patterns']
            _bp['additional_notes'] = (_bp.get('additional_notes') or "") + f"我重新生成了第 {selected_sid} 个环节的内容。\n"
            st.session_state["current_page"][session_uid] = 0
            st.rerun()

    with col4:
        complete_button_status = True if session_info["if_learned"] else False

        if st.button("完成环节",
                     key="complete-session-bottom", type="primary", icon=":material/task_alt:",
                     use_container_width=True, disabled=complete_button_status or st.session_state["if_updating_learner_profile"]):
            trigger_session_completion(goal)

        if st.session_state.get("if_updating_learner_profile"):
            # 携带环节完成事件与（若已有）测验得分，让后端 LLM 相应更新画像
            cached_content = st.session_state["document_caches"].get(get_current_session_uid(), {}) or {}
            quiz_score = cached_content.get("quiz_score") or {}
            message = f"{session_info.get('id', '本环节')} 已完成。"
            if quiz_score:
                message += f"完成前测验得分：{quiz_score.get('score_percentage', 0)}%（{quiz_score.get('correct_count', 0)}/{quiz_score.get('total_count', 0)}）。"
            feedback_data = {
                "interaction_type": "session_completed",
                "message": message,
            }
            update_result = update_learner_profile_with_feedback(
                goal, feedback_data, session_information=session_info, mark_session_learned=True
            )
            st.session_state["if_updating_learner_profile"] = False
            try:
                save_persistent_state()
            except Exception:
                pass
            if not update_result:
                st.toast("更新学习者资料失败，请重试。")
                st.rerun()
            else:
                st.toast("环节完成！")
                goal["learning_path"][selected_sid]["if_learned"] = True
                st.session_state["selected_page"] = "Learning Path"
                try:
                    save_persistent_state()
                except Exception:
                    pass
                if get_current_session_uid() in st.session_state["session_learning_times"]:
                    curr_time = time.time()
                    st.session_state["session_learning_times"][get_current_session_uid()]["end_time"] = curr_time

                save_persistent_state()
                st.switch_page("app_pages/learning_path.py")

    # 环节编号以中文显示（数据层的 id 保持 "Session N"格式不变）
    st.markdown(f"# {str(session_info['id']).replace('Session', '环节')}")
    st.markdown(f"# {session_info['title']}")

    with st.container(border=True):
        st.info(session_info["abstract"])
        associated_skills = session_info["associated_skills"]
        st.write("**关联技能：**")
        for i, skill_name in enumerate(associated_skills):
            st.write(f"- {skill_name}")

def render_content_preparation(goal):
    selected_sid = st.session_state["selected_session_id"]
    learning_session = goal["learning_path"][selected_sid]
    session_uid = get_current_session_uid()
    if use_mock_data:
        st.warning("正在使用模拟数据生成知识文档。")
        file_path = "./assets/data_example/knowledge_document.json"
        learning_content = load_knowledge_point_content(file_path)
        st.session_state["document_caches"][session_uid] = learning_content
        try:
            save_persistent_state()
        except Exception:
            pass
        return learning_content

    with st.status("正在生成学习内容…（快速模型，约 1 分钟）", expanded=True) as status:
        st.write("第 1/4 步：探索知识点…")
        knowledge_points = explore_knowledge_points(
            goal["learner_profile"],
            goal["learning_path"],
            learning_session,
            llm_type="gpt4o"
        )
        if knowledge_points is None:
            status.update(label="知识点探索失败", state="error", expanded=True)
            st.error("探索知识点失败。")
            return
        st.write(f"已探索 {len(knowledge_points)} 个知识点：" + "、".join(kp["name"] for kp in knowledge_points))
        # 知识点随后会随 learning_content 一起写入 document_caches[session_uid]，
        # 图谱与配图统一从该按 session_uid 键控的缓存读取，不再写全局变量以免跨环节串数据。

        st.write("第 2/4 步：起草知识点…")
        knowledge_drafts = draft_knowledge_points(
            goal["learner_profile"],
            goal["learning_path"],
            learning_session,
            knowledge_points,
            use_search=use_search,
            allow_parallel=True,
            llm_type="gpt4o"
        )
        if knowledge_drafts is None:
            status.update(label="知识点起草失败", state="error", expanded=True)
            st.error("起草知识点失败。")
            return
        st.write(f"已完成 {len(knowledge_drafts)} 个知识点起草")

        st.write("第 3/4 步：整合知识文档…")
        document_structure = integrate_learning_document(
            goal["learner_profile"],
            goal["learning_path"],
            learning_session,
            knowledge_points,
            knowledge_drafts,
            llm_type="gpt4o",
            output_markdown=False
        )
        learning_document = prepare_markdown_document(document_structure, knowledge_points, knowledge_drafts)
        if learning_document is None:
            status.update(label="知识文档整合失败", state="error", expanded=True)
            st.error("整合知识文档失败。")
            return
        st.write("知识文档整合完成")

        st.write("第 4/4 步：生成文档测验…")
        quizzes = generate_document_quizzes(
            goal["learner_profile"],
            learning_document,
            single_choice_count=3,
            multiple_choice_count=1,
            true_false_count=1,
            short_answer_count=1,
            llm_type="gpt4o"
        )
        st.write("文档测验生成完成")

    status.update(label="学习内容生成完成", state="complete", expanded=False)
    learning_content = {"document": learning_document, "followup_rounds": [], "quizzes": quizzes}

    # 保存知识点到缓存供知识图谱使用
    learning_content["knowledge_points"] = knowledge_points

    # 自动为知识点生成配图（后台进行，不阻塞文档显示）
    st.caption("正在自动生成知识点配图…")
    try:
        image_result = generate_session_images(
            knowledge_points=knowledge_points,
            session_title=learning_session.get("title", ""),
            session_abstract=learning_session.get("abstract", ""),
            visual_style="educational",
            size="1024x1024",
            max_images=min(5, len(knowledge_points))
        )
        if image_result is None:
            st.warning("配图生成无返回结果（可能后端服务异常），可稍后手动重试")
        else:
            images = image_result.get("images") or []
            if images:
                successful_count = sum(1 for img in images if img.get("image_url"))
                _auto_save_kp_images(session_uid, images)
                if successful_count > 0:
                    st.success(f"已自动生成 {len(images)} 张知识点配图（其中 {successful_count} 张成功获取图片），可在配图库查看")
                else:
                    st.warning(f"生成 {len(images)} 张配图记录，但图片搜索全部失败（网络问题），可在配图库手动重试")
            else:
                # LLM 评估后认为本会话没有值得配图的知识点，属正常情况，不生成图片
                st.info("本次未生成配图：经评估本会话没有适合可视化的知识点。")
            # 豆包生图不可用时的原因（欠费/模型未开通/额度受限等）
            if image_result.get("notice"):
                st.warning(image_result["notice"])
    except Exception as e:
        st.error(f"配图生成失败: {e}")

    st.session_state["document_caches"][session_uid] = learning_content
    try:
        save_persistent_state()
    except Exception:
        pass

    # 首次生成：以打字机方式流出整篇文档，随后进入分页阅读
    st.subheader(learning_session.get("title", "学习文档"))
    st.write_stream(_stream_text(learning_document))
    st.info("已整理为分页阅读模式，正在进入…")
    time.sleep(1.5)
    st.rerun()
    return learning_content


def _stream_text(text, chunk_size=90, delay=0.02):
    """把整篇文档切成小块逐段输出，形成打字机流式效果。"""
    for para in (text or "").split("\n\n"):
        if not para.strip():
            continue
        for i in range(0, len(para), chunk_size):
            yield para[i:i + chunk_size]
            time.sleep(delay)
        yield "\n\n"


# ---------------------------------------------------------------------------
# Quiz 反馈闭环：轮次状态、作答采集、诊断与画像更新
# ---------------------------------------------------------------------------

def ensure_followup_rounds_state(learning_content):
    if "followup_rounds"not in learning_content or not isinstance(learning_content.get("followup_rounds"), list):
        learning_content["followup_rounds"] = []
    return learning_content["followup_rounds"]


def ensure_round_state(round_state):
    if "quiz_attempts"not in round_state or not isinstance(round_state.get("quiz_attempts"), dict):
        round_state["quiz_attempts"] = {}
    if "generation_context"not in round_state or not isinstance(round_state.get("generation_context"), dict):
        round_state["generation_context"] = {}
    return round_state


def get_learning_rounds(learning_content):
    """返回全部学习轮次：基础轮 + 各个补强轮。"""
    ensure_round_state(learning_content)
    followup_rounds = ensure_followup_rounds_state(learning_content)
    for round_state in followup_rounds:
        ensure_round_state(round_state)
    return [learning_content] + followup_rounds


def get_active_round_state(learning_content):
    """根据当前阅读页返回激活中的轮次（基础轮或某个补强轮）。"""
    round_index = st.session_state.get("active_followup_round_index")
    followup_rounds = ensure_followup_rounds_state(learning_content)
    if round_index and 1 <= round_index <= len(followup_rounds):
        return ensure_round_state(followup_rounds[round_index - 1])
    return learning_content


def _stringify_answer(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return "未作答"
    return str(value)


def _resolve_option_value(options, option_or_index):
    if isinstance(option_or_index, int):
        if 0 <= option_or_index < len(options):
            return options[option_or_index]
        return str(option_or_index)
    if isinstance(option_or_index, str):
        if option_or_index in options:
            return option_or_index
        try:
            option_index = int(option_or_index)
        except Exception:
            return option_or_index
        if 0 <= option_index < len(options):
            return options[option_index]
    return str(option_or_index)


def build_quiz_entries(quiz_data):
    """把四类题目规整为统一的 entries 列表，correct_answer 一律还原为选项文本。"""
    quiz_entries = []
    for i, q in enumerate(quiz_data.get("single_choice_questions", []) or []):
        quiz_entries.append({
            "question_id": f"single_choice_{i}",
            "question_type": "single_choice",
            "question": q["question"],
            "options": q.get("options", []),
            "correct_answer": _resolve_option_value(q.get("options", []), q.get("correct_option")),
            "explanation": q.get("explanation") or "",
        })
    for i, q in enumerate(quiz_data.get("multiple_choice_questions", []) or []):
        quiz_entries.append({
            "question_id": f"multiple_choice_{i}",
            "question_type": "multiple_choice",
            "question": q["question"],
            "options": q.get("options", []),
            "correct_answer": [_resolve_option_value(q.get("options", []), option) for option in q.get("correct_options", [])],
            "explanation": q.get("explanation") or "",
        })
    for i, q in enumerate(quiz_data.get("true_false_questions", []) or []):
        quiz_entries.append({
            "question_id": f"true_false_{i}",
            "question_type": "true_false",
            "question": q["question"],
            "options": ["正确", "错误"],
            "correct_answer": "正确"if q.get("correct_answer") else "错误",
            "explanation": q.get("explanation") or "",
        })
    for i, q in enumerate(quiz_data.get("short_answer_questions", []) or []):
        quiz_entries.append({
            "question_id": f"short_answer_{i}",
            "question_type": "short_answer",
            "question": q["question"],
            "options": [],
            "correct_answer": q.get("expected_answer", ""),
            "explanation": q.get("explanation") or "",
        })
    return quiz_entries


def normalize_text_answer(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def evaluate_quiz_answer(question_type, user_answer, correct_answer):
    """客观题本地判分；简答题精确匹配为对，否则交给后端 LLM 语义判分（返回 None）。"""
    if question_type == "single_choice":
        return normalize_text_answer(user_answer) == normalize_text_answer(correct_answer)
    if question_type == "multiple_choice":
        normalized_user = {normalize_text_answer(item) for item in (user_answer or []) if str(item).strip()}
        normalized_correct = {normalize_text_answer(item) for item in (correct_answer or []) if str(item).strip()}
        return normalized_user == normalized_correct
    if question_type == "true_false":
        return normalize_text_answer(user_answer) == normalize_text_answer(correct_answer)
    if question_type == "short_answer":
        if normalize_text_answer(user_answer) == normalize_text_answer(correct_answer):
            return True
        return None
    return None


def build_attempt_payload(entry, user_answer):
    return {
        "question_id": entry["question_id"],
        "question_type": entry["question_type"],
        "question": entry["question"],
        "options": entry.get("options", []),
        "user_answer": user_answer,
        "correct_answer": entry["correct_answer"],
        "explanation": entry.get("explanation", ""),
        "is_submitted": True,
        "is_correct": evaluate_quiz_answer(entry["question_type"], user_answer, entry["correct_answer"]),
    }


def ensure_quiz_attempt_state(round_state, quiz_entries):
    """初始化/同步当前轮次的作答状态，清理失效题目，保留已作答内容。"""
    ensure_round_state(round_state)
    quiz_attempts = round_state.setdefault("quiz_attempts", {})
    valid_question_ids = {entry["question_id"] for entry in quiz_entries}

    for stale_question_id in list(quiz_attempts.keys()):
        if stale_question_id not in valid_question_ids:
            quiz_attempts.pop(stale_question_id, None)

    for entry in quiz_entries:
        current = quiz_attempts.setdefault(entry["question_id"], {})
        desired_values = {
            "question_id": entry["question_id"],
            "question_type": entry["question_type"],
            "question": entry["question"],
            "options": entry.get("options", []),
            "correct_answer": entry["correct_answer"],
            "explanation": entry.get("explanation", ""),
            "user_answer": current.get("user_answer"),
            "is_submitted": current.get("is_submitted", False),
            "is_correct": current.get("is_correct"),
        }
        quiz_attempts[entry["question_id"]] = desired_values


def get_ordered_quiz_attempts(round_state, quiz_entries=None):
    quiz_attempts = round_state.get("quiz_attempts", {})
    if quiz_entries is None:
        return list(quiz_attempts.values())
    ordered_attempts = []
    for entry in quiz_entries:
        attempt = quiz_attempts.get(entry["question_id"])
        if attempt:
            ordered_attempts.append(attempt)
    return ordered_attempts


def get_submitted_quiz_attempts(round_state, quiz_entries=None):
    return [attempt for attempt in get_ordered_quiz_attempts(round_state, quiz_entries) if attempt.get("is_submitted")]


def get_submitted_quiz_results(round_state, quiz_entries=None):
    results = []
    for attempt in get_submitted_quiz_attempts(round_state, quiz_entries):
        results.append({
            "question_type": attempt.get("question_type"),
            "question": attempt.get("question", ""),
            "user_answer": _stringify_answer(attempt.get("user_answer")),
            "correct_answer": _stringify_answer(attempt.get("correct_answer")),
            "is_correct": attempt.get("is_correct"),
            "explanation": attempt.get("explanation", ""),
        })
    return results


def compute_quiz_analysis_signature(round_state, quiz_entries):
    """以已提交作答内容生成签名，用于避免重复触发诊断。"""
    submitted_attempts = get_submitted_quiz_attempts(round_state, quiz_entries)
    normalized_attempts = [
        {
            "question_id": attempt.get("question_id"),
            "question_type": attempt.get("question_type"),
            "user_answer": attempt.get("user_answer"),
            "correct_answer": attempt.get("correct_answer"),
        }
        for attempt in submitted_attempts
    ]
    signature_source = json.dumps(normalized_attempts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(signature_source.encode("utf-8")).hexdigest()


def apply_quiz_analysis_to_attempts(round_state, analysis):
    """把 LLM 的逐题判定回写到本地作答状态（主要纠正简答题）。"""
    ensure_round_state(round_state)
    question_evaluations = analysis.get("question_evaluations") or []
    for evaluation in question_evaluations:
        question_id = evaluation.get("question_id")
        if not question_id:
            continue
        attempt = round_state["quiz_attempts"].get(question_id)
        if not attempt:
            continue
        for field_name in ["question", "question_type", "user_answer", "correct_answer", "explanation"]:
            if evaluation.get(field_name) is not None:
                attempt[field_name] = evaluation.get(field_name)
        if attempt.get("is_correct") != evaluation.get("is_correct"):
            attempt["is_correct"] = evaluation.get("is_correct")


def resolve_quiz_score(round_state, analysis, quiz_entries):
    """分析分数优先，本地计算兜底。"""
    submitted_attempts = get_submitted_quiz_attempts(round_state, quiz_entries)
    total_count = len(quiz_entries)
    if total_count == 0 or len(submitted_attempts) != total_count:
        return None

    correct_count = sum(1 for attempt in submitted_attempts if attempt.get("is_correct") is True)
    computed_score = {
        "correct_count": correct_count,
        "total_count": total_count,
        "score_percentage": round((correct_count / total_count) * 100, 2),
    }
    analysis_score = (analysis or {}).get("score") or {}
    if analysis_score.get("total_count") == total_count:
        return {
            "correct_count": analysis_score.get("correct_count", computed_score["correct_count"]),
            "total_count": total_count,
            "score_percentage": analysis_score.get("score_percentage", computed_score["score_percentage"]),
        }
    return computed_score


def refresh_quiz_analysis(goal, round_state, session_information, quiz_entries, force=False):
    """全部题目提交后调用后端诊断，并回写判定与得分。"""
    submitted_attempts = get_submitted_quiz_attempts(round_state, quiz_entries)
    if not submitted_attempts or len(submitted_attempts) != len(quiz_entries):
        return round_state.get("quiz_analysis")

    signature = compute_quiz_analysis_signature(round_state, quiz_entries)
    if not force and signature == round_state.get("quiz_analysis_signature") and round_state.get("quiz_analysis"):
        return round_state.get("quiz_analysis")

    round_state["quiz_analysis_requested_signature"] = signature
    with st.spinner("正在根据答题情况生成学习诊断..."):
        analysis = analyze_document_quiz(
            goal["learner_profile"],
            submitted_attempts,
            session_information=session_information,
            llm_type="gpt4o",
        )
    if analysis is not None:
        round_state["quiz_analysis"] = analysis
        apply_quiz_analysis_to_attempts(round_state, analysis)
        score = resolve_quiz_score(round_state, analysis, quiz_entries)
        if score is not None:
            round_state["quiz_score"] = score
        round_state["quiz_analysis_signature"] = signature
        round_state["quiz_analysis_updated_at"] = time.time()
        try:
            save_persistent_state()
        except Exception:
            pass
    return analysis


def build_profile_update_additional_info_from_quiz_analysis(quiz_analysis):
    """把薄弱点与建议整理为面向后续内容生成的长期教学提示。"""
    if not quiz_analysis:
        return ""

    weak_points = quiz_analysis.get("weak_points") or []
    recommendations = quiz_analysis.get("recommendations") or []
    if not weak_points and not recommendations:
        return ""

    lines = ["请将下面信息作为后续 session 讲解方式与内容侧重点的长期提示。"]
    if weak_points:
        lines.append("学习者当前暴露出的薄弱点：")
        for point in weak_points:
            lines.append(f"- {point}")
    if recommendations:
        lines.append("后续讲解提示：")
        for recommendation in recommendations:
            lines.append(f"- {recommendation}")
    return "\n".join(lines)


def build_quiz_profile_feedback_data(round_state, quiz_entries, round_label):
    quiz_analysis = round_state.get("quiz_analysis") or {}
    return {
        "interaction_type": "quiz_submission",
        "quiz_round": round_label,
        "user_quiz_results": get_submitted_quiz_results(round_state, quiz_entries),
        "quiz_analysis": quiz_analysis,
        "additional_info": build_profile_update_additional_info_from_quiz_analysis(quiz_analysis),
    }


def refresh_learner_profile_from_quiz(goal, round_state, session_information, quiz_entries, round_label, force=False):
    """把测验结果与诊断写入 learner_profile，供后续内容生成使用。"""
    quiz_analysis = round_state.get("quiz_analysis")
    analysis_signature = round_state.get("quiz_analysis_signature")
    if not quiz_analysis or not analysis_signature:
        return False

    if not force and round_state.get("quiz_profile_update_signature") == analysis_signature:
        return False

    learner_interactions = build_quiz_profile_feedback_data(round_state, quiz_entries, round_label)
    with st.spinner("正在根据测验结果更新学习者画像..."):
        update_result = update_learner_profile_with_feedback(
            goal,
            learner_interactions,
            session_information=session_information,
            mark_session_learned=False,
            show_toast=False,
        )

    round_state["quiz_profile_update_signature"] = analysis_signature
    round_state["quiz_profile_update_success"] = bool(update_result)
    round_state["quiz_profile_updated_at"] = time.time()
    try:
        save_persistent_state()
    except Exception:
        pass
    return bool(update_result)


def render_quiz_analysis(round_state, quiz_entries):
    total_count = len(quiz_entries)
    submitted_attempts = get_submitted_quiz_attempts(round_state, quiz_entries)
    submitted_count = len(submitted_attempts)

    st.subheader("学习诊断")
    summary_col_1, summary_col_2, summary_col_3 = st.columns(3)
    summary_col_1.metric("已提交", f"{submitted_count}/{total_count}")

    if submitted_count < total_count:
        st.info("完成全部题目并提交后，系统会自动结合你的作答情况和学习者画像生成掌握点与薄弱点分析。")
        return

    analysis = round_state.get("quiz_analysis")
    if not analysis:
        st.warning("题目已全部提交，但学习诊断暂未生成成功。你可以重新提交任意一道题再次触发分析。")
        return

    score = resolve_quiz_score(round_state, analysis, quiz_entries)
    if score is not None:
        summary_col_2.metric("答对", f"{score['correct_count']}/{score['total_count']}")
        summary_col_3.metric("得分", f"{score['score_percentage']:.1f}%")
        round_state["quiz_score"] = score

    if analysis.get("overall_summary"):
        st.info(analysis["overall_summary"])

    mastery_col, weak_col = st.columns(2)
    with mastery_col:
        with st.container(border=True):
            st.write("**掌握点**")
            for point in analysis.get("mastery_points", []):
                st.write(f"- {point}")
    with weak_col:
        with st.container(border=True):
            st.write("**薄弱点**")
            for point in analysis.get("weak_points", []):
                st.write(f"- {point}")


def render_followup_generation_context(round_state):
    generation_context = round_state.get("generation_context") or {}
    if not generation_context:
        return

    previous_score = generation_context.get("previous_score") or {}
    wrong_questions = generation_context.get("wrong_questions") or []
    weak_points = generation_context.get("weak_points") or []
    recommendations = generation_context.get("recommendations") or []

    with st.expander("查看本轮生成依据", expanded=False):
        if previous_score:
            st.write(
                f"**上一轮得分：** {previous_score.get('score_percentage', 0)}% "
                f"({previous_score.get('correct_count', 0)}/{previous_score.get('total_count', 0)})"
            )
        if wrong_questions:
            st.write("**上一轮错题回顾**")
            for item in wrong_questions:
                with st.container(border=True):
                    st.write(f"**题目：** {item.get('question', '')}")
                    st.write(f"**你的答案：** {_stringify_answer(item.get('user_answer'))}")
                    st.write(f"**标准答案：** {_stringify_answer(item.get('correct_answer'))}")
                    st.write(f"**解释：** {item.get('explanation') or '暂无解释'}")
        if weak_points:
            st.write("**薄弱点分析**")
            for point in weak_points:
                st.write(f"- {point}")
        if recommendations:
            st.write("**后续学习建议**")
            for recommendation in recommendations:
                st.write(f"- {recommendation}")


def render_continue_learning_controls(goal, learning_content, round_state, session_information, previous_quiz):
    """诊断就绪后提供"继续学习"入口：基于薄弱点生成下一轮内容与新测验。"""
    analysis = round_state.get("quiz_analysis")
    if not analysis:
        return

    latest_round_state = get_learning_rounds(learning_content)[-1]
    if latest_round_state is not round_state:
        st.caption("已基于本轮结果生成后续学习内容。")
        return

    score = round_state.get("quiz_score") or analysis.get("score") or {}
    st.write("### 继续学习")
    if score:
        st.caption(
            f"当前得分：{score.get('score_percentage', 0)}% "
            f"({score.get('correct_count', 0)}/{score.get('total_count', 0)})"
        )
    mode_col, action_col = st.columns([3, 2])
    with mode_col:
        selected_mode_label = st.selectbox(
            "继续学习模式",
            [
                "模式A：补强内容 + 新测验",
                "模式B：快速回顾 + 新测验",
            ],
            key=f"{get_current_session_uid()}_continue_mode_{round_state.get('round_index', 0)}",
        )
    selected_mode = "A"if selected_mode_label.startswith("模式A") else "B"
    with action_col:
        if st.button(
            "继续学习",
            key=f"{get_current_session_uid()}_continue_button_{round_state.get('round_index', 0)}",
            type="primary",
            use_container_width=True,
            icon=":material/arrow_circle_right:",
        ):
            quiz_entries = build_quiz_entries(previous_quiz)
            submitted_attempts = get_submitted_quiz_attempts(round_state, quiz_entries)
            next_round_index = len(ensure_followup_rounds_state(learning_content)) + 1
            with st.spinner("正在生成下一轮学习内容..."):
                followup_round = generate_followup_learning_round(
                    goal["learner_profile"],
                    goal["learning_path"],
                    session_information,
                    submitted_attempts,
                    analysis,
                    previous_quiz,
                    mode=selected_mode,
                    round_index=next_round_index,
                    allow_parallel=True,
                    use_search=use_search,
                )
            if followup_round is None:
                st.error("继续学习内容生成失败，请稍后重试。")
                return
            ensure_round_state(followup_round)
            followup_round["round_index"] = next_round_index
            ensure_followup_rounds_state(learning_content).append(followup_round)
            # 跳转到新补强轮页面（基础文档分页数在渲染函数内计算，这里先按最大页处理）
            st.session_state["current_page"][get_current_document_page_key()] = 10 ** 6
            try:
                save_persistent_state()
            except Exception:
                pass
            st.rerun()


def get_current_document_page_key():
    selected_gid = st.session_state["selected_goal_id"]
    session_id = st.session_state["selected_session_id"]
    return f"{selected_gid}-{session_id}"


def render_multimodal_image_generation_section(goal, learning_session, knowledge_points):
    """在内容渲染阶段显示多模态内容生成功能

    知识点配图现在会自动生成并嵌入文档内容，无需手动操作。
    这里只保留知识结构图（思维导图等）的手动生成入口。
    """
    session_uid = get_current_session_uid()

    with st.expander("多模态内容 - 知识结构图、已生成配图库", expanded=True):
        # Tab 1: 知识结构图（保留手动生成）
        tab1, tab2 = st.tabs(["知识结构图", "配图库"])

        with tab1:
            st.info("生成知识结构图（思维导图、知识树等），帮助整体理解知识框架")

            # 初始化图像模态框状态
            if 'image_modal_open'not in st.session_state:
                st.session_state['image_modal_open'] = None

            # 根据模态框状态决定是否展开 expander
            is_modal_open = st.session_state.get('image_modal_open') is not None

            # 快速选择常用图像类型
            col1, col2, col3 = st.columns(3)

            with col1:
                if st.button("思维导图", key=f"mind_map_{session_uid}", use_container_width=True):
                    st.session_state['image_modal_open'] = 'mind_map'
                    st.rerun()

            with col2:
                if st.button("知识树", key=f"tree_{session_uid}", use_container_width=True):
                    st.session_state['image_modal_open'] = 'knowledge_tree'
                    st.rerun()

            with col3:
                if st.button("学习路线图", key=f"roadmap_{session_uid}", use_container_width=True):
                    st.session_state['image_modal_open'] = 'learning_roadmap'
                    st.rerun()

            # 根据状态渲染模态框
            if st.session_state.get('image_modal_open'):
                render_image_generator_modal(goal, learning_session, knowledge_points, st.session_state['image_modal_open'])

            # 显示已生成的结构图
            _render_generated_structure_images(session_uid)

        with tab2:
            # 配图库：展示所有已生成的知识点配图（兜底，在文档嵌入之外也能看到）
            kp_images = st.session_state.get('kp_images', {}).get(session_uid, {})
            if kp_images:
                st.info(f"已生成 {len(kp_images)} 张知识点配图，可浏览或重新生成")
            _render_knowledge_point_images(session_uid)

        # 已生成的所有图像（通用）
        if session_uid in st.session_state.get('generated_images', {}):
            st.divider()
            st.subheader("已生成的所有图像")
            _render_all_generated_images(session_uid)


def _render_generated_structure_images(session_uid):
    """渲染已生成的知识结构图"""
    if session_uid in st.session_state.get('generated_images', {}):
        images = st.session_state['generated_images'][session_uid]
        structure_types = ['mind_map', 'knowledge_tree', 'learning_roadmap', 'concept_diagram', 'summary_poster']
        structure_images = [img for img in images if img.get('image_type') in structure_types]

        if structure_images:
            st.markdown("** 知识结构图**:")

            for idx, img_info in enumerate(structure_images):
                with st.container(border=True):
                    type_labels = {
                        "mind_map": "思维导图",
                        "knowledge_tree": "知识树",
                        "concept_diagram": "概念图",
                        "learning_roadmap": "学习路线图",
                        "summary_poster": "总结海报"
                    }
                    type_name = type_labels.get(img_info['image_type'], img_info['image_type'])
                    st.markdown(f"**{type_name}**")
                    st.image(_image_source(img_info['image_url']), use_container_width=True)


def _render_knowledge_point_images(session_uid):
    """渲染已生成的知识点配图"""
    if 'kp_images'not in st.session_state:
        st.session_state['kp_images'] = {}

    kp_images = st.session_state['kp_images'].get(session_uid, {})

    if kp_images:
        cols = st.columns(min(len(kp_images), 3))

        for idx, (kp_name, img_info) in enumerate(kp_images.items()):
            col_idx = idx % len(cols)
            with cols[col_idx]:
                with st.container(border=True):
                    st.markdown(f"**{kp_name}**")

                    style_label = {
                        "educational": "",
                        "realistic": "",
                        "diagrammatic": "",
                        "infographic": "",
                        "minimalist": "",
                        "colorful": ""
                    }
                    style = img_info.get('visual_style', 'educational')
                    st.markdown(f"{style_label.get(style, '')} `{style}`")

                    if img_info.get('image_url'):
                        st.image(_image_source(img_info['image_url']), use_container_width=True)

                    _btn_col1, _btn_col2 = st.columns([2, 1])
                    with _btn_col1:
                        if st.button("重新生成", icon=":material/refresh:", key=f"regen_kp_{session_uid}_{kp_name}"):
                            # 删除缓存，下次可重新生成
                            del st.session_state['kp_images'][session_uid][kp_name]
                            st.rerun()
                    with _btn_col2:
                        if st.button("删除", icon=":material/delete:", key=f"del_kp_{session_uid}_{kp_name}"):
                            del st.session_state['kp_images'][session_uid][kp_name]
                            st.rerun()
    else:
        st.warning("还没有生成任何知识点配图。如果之前生成失败，可以点击下方「 生成配图」按钮重试")


def _render_all_generated_images(session_uid):
    """渲染所有已生成的图像"""
    all_images = []

    # 收集结构图
    if session_uid in st.session_state.get('generated_images', {}):
        all_images.extend(st.session_state['generated_images'][session_uid])

    # 收集知识点配图
    if 'kp_images'in st.session_state and session_uid in st.session_state['kp_images']:
        for kp_name, img_info in st.session_state['kp_images'][session_uid].items():
            all_images.append({
                **img_info,
                'image_type': 'knowledge_point',
                'knowledge_point_name': kp_name
            })

    if all_images:
        for idx, img_info in enumerate(all_images):
            with st.container(border=True):
                col_img, col_del = st.columns([5, 1])

                with col_img:
                    if img_info.get('image_type') == 'knowledge_point':
                        kp_name = img_info.get('knowledge_point_name', '知识点')
                        st.markdown(f" **知识点配图: {kp_name}**")
                    else:
                        type_labels = {
                            "mind_map": "思维导图",
                            "knowledge_tree": "知识树",
                            "concept_diagram": "概念图",
                            "learning_roadmap": "学习路线图",
                            "summary_poster": "总结海报"
                        }
                        type_name = type_labels.get(img_info['image_type'], img_info['image_type'])
                        st.markdown(f" **{type_name}**")

                    st.image(_image_source(img_info['image_url']), use_container_width=True)

                with col_del:
                    if st.button("删除", icon=":material/delete:", key=f"del_all_img_{session_uid}_{idx}"):
                        # TODO: 删除逻辑
                        pass


def render_knowledge_point_image_generator(goal, learning_session, knowledge_points, batch_mode: bool = False):
    """渲染知识点配图生成器（批量或单个模式）"""
    session_uid = get_current_session_uid()

    # 配置参数
    col1, col2, col3 = st.columns(3)

    with col1:
        visual_style = st.selectbox(
            "视觉风格",
            options=[
                ("educational", "教育风格"),
                ("realistic", "真实风格"),
                ("diagrammatic", "图表风格"),
                ("infographic", "信息图表"),
                ("minimalist", "简约风格"),
                ("colorful", "彩色风格")
            ],
            format_func=lambda x: x[1],
            key=f"visual_style_batch_{session_uid}"
        )[0]

    with col2:
        size = st.selectbox(
            "图像尺寸",
            options=["1024x1024", "1792x1024", "1024x1792"],
            key=f"size_batch_{session_uid}"
        )

    with col3:
        max_images = st.slider(
            "最多生成数量",
            min_value=1,
            max_value=min(10, len(knowledge_points)),
            value=min(5, len(knowledge_points)),
            key=f"max_images_batch_{session_uid}"
        )

    # 批量生成进度条
    if batch_mode:
        st.divider()
        st.markdown("###  将为以下知识点生成配图:")

        for i, kp in enumerate(knowledge_points[:max_images]):
            st.markdown(f"{i+1}. **{kp.get('name', f'知识点{i+1}')}**")

        if st.button(f"开始批量生成", key=f"start_batch_gen_{session_uid}", type="primary"):
            _perform_batch_image_generation(
                knowledge_points[:max_images],
                session_uid,
                learning_session,
                visual_style,
                size
            )
    else:
        st.divider()
        st.markdown(f"### 将为 **{max_images}** 个知识点生成配图")

        if st.button(f"开始批量生成", key=f"start_batch_gen_{session_uid}", type="primary"):
            _perform_batch_image_generation(
                knowledge_points[:max_images],
                session_uid,
                learning_session,
                visual_style,
                size
            )


def _perform_batch_image_generation(knowledge_points, session_uid, learning_session, visual_style, size):
    """执行批量图片生成"""
    # 初始化进度
    if 'kp_batch_progress'not in st.session_state:
        st.session_state['kp_batch_progress'] = {}

    total = len(knowledge_points)
    success_count = 0
    failed_kps = []
    fallback_notice = None

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, kp in enumerate(knowledge_points):
        kp_name = kp.get('name', f'知识点{i+1}')
        status_text.text(f"正在生成第 {i+1}/{total} 个知识点的配图: {kp_name}")

        try:
            result = generate_knowledge_point_image(
                knowledge_point=kp,
                session_title=learning_session.get("title", ""),
                session_abstract=learning_session.get("abstract", ""),
                visual_style=visual_style,
                size=size
            )

            if result and result.get("success"):
                _save_knowledge_point_image(session_uid, result)
                success_count += 1
                if result.get("doubao_fallback_notice"):
                    fallback_notice = result["doubao_fallback_notice"]
            else:
                failed_kps.append(kp_name)

        except Exception as e:
            st.error(f"生成「{kp_name}」配图时出错: {e}")
            failed_kps.append(kp_name)

        # 更新进度
        progress = (i + 1) / total
        progress_bar.progress(progress)

    # 显示结果
    st.divider()
    if success_count == total:
        st.success(f"批量生成完成！成功获取 {success_count} 张知识点配图！")
    else:
        st.warning(f"批量生成完成！成功 {success_count}/{total} 张")
        if failed_kps:
            with st.expander("获取失败的知识点"):
                for kp_name in failed_kps:
                    st.write(f"- {kp_name}")

    # 豆包生图不可用时的原因（欠费/模型未开通/额度受限等）
    if fallback_notice:
        st.warning(fallback_notice)

    # 保存配图到持久化存储
    try:
        save_persistent_state()
    except Exception:
        pass


# 自动配图请求失败后的冷却时长（秒）：失败后短时间内不再自动重试，避免每次 rerun 重发整批请求。
_KP_IMAGES_RETRY_COOLDOWN_SECONDS = 60


def _ensure_kp_images_auto_generated(session_uid, knowledge_points, learning_session):
    """确保知识点配图已自动生成，如果没有则触发生成"""
    if not knowledge_points:
        return

    # 检查是否已有配图
    existing_images = st.session_state.get('kp_images', {}).get(session_uid, {})
    if existing_images and len(existing_images) > 0:
        # 已有配图，不需要重复生成
        return

    # 已经尝试过（含 LLM 评估为"无需配图"）就不再重复规划，避免每次 rerun 都重新跑一遍
    attempted = st.session_state.setdefault('_kp_images_attempted', set())
    if session_uid in attempted:
        return

    # 处于失败冷却期：跳过自动重试（此前失败不记状态，后端异常时每次 rerun 都会重发
    # 整批生图请求、单个请求超时上限达 1 小时，界面被反复阻塞）。手动「配图库」重试不走这里，不受影响。
    if time.time() < st.session_state.get('_kp_images_retry_after', 0):
        return

    # 检查是否正在生成中（避免重复触发）
    if st.session_state.get('_is_generating_kp_images'):
        return

    # 标记正在生成
    st.session_state['_is_generating_kp_images'] = True

    # 触发图片生成
    with st.spinner("正在自动生成知识点配图..."):
        try:
            image_result = generate_session_images(
                knowledge_points=knowledge_points,
                session_title=learning_session.get("title", ""),
                session_abstract=learning_session.get("abstract", ""),
                visual_style="educational",
                size="1024x1024",
                max_images=min(5, len(knowledge_points))
            )
            if image_result is None:
                # 后端异常：进入冷却，冷却期内不再自动重试（手动「配图库」重试仍可用）
                st.session_state['_kp_images_retry_after'] = time.time() + _KP_IMAGES_RETRY_COOLDOWN_SECONDS
                st.info("配图生成无返回结果（可能后端服务异常），可稍后手动重试")
            else:
                attempted.add(session_uid)
                st.session_state.pop('_kp_images_retry_after', None)
                images = image_result.get("images") or []
                if images:
                    _auto_save_kp_images(session_uid, images)
                    st.toast(f"已自动生成 {len(images)} 张知识点配图")
                else:
                    # LLM 评估后认为本会话没有值得配图的知识点，属正常情况
                    st.info("本次未生成配图：经评估本会话没有适合可视化的知识点")
                # 豆包生图不可用时的原因（欠费/模型未开通/额度受限等）
                if image_result.get("notice"):
                    st.warning(image_result["notice"])
        except Exception as e:
            st.session_state['_kp_images_retry_after'] = time.time() + _KP_IMAGES_RETRY_COOLDOWN_SECONDS
            st.warning(f"知识点配图自动生成失败: {e}")
        finally:
            # 清除生成标记
            st.session_state['_is_generating_kp_images'] = False


def _auto_save_kp_images(session_uid, image_results):
    """自动保存批量生成的知识点配图（不覆盖手动重新生成的）"""
    if 'kp_images'not in st.session_state:
        st.session_state['kp_images'] = {}
    if session_uid not in st.session_state['kp_images']:
        st.session_state['kp_images'][session_uid] = {}

    saved_count = 0
    for result in image_results:
        # 只要有 image_url 就保存（不强制检查 success 字段）
        image_url = result.get('image_url')
        if image_url:
            kp_name = result.get('knowledge_point_name', 'Unknown')
            # 仅当该知识点尚无配图时自动保存（允许手动重新生成覆盖）
            if kp_name not in st.session_state['kp_images'][session_uid]:
                st.session_state['kp_images'][session_uid][kp_name] = result
                saved_count += 1
                print(f"[配图保存] {kp_name}: {image_url[:50]}...")
    
    print(f"[配图保存] 共保存 {saved_count}/{len(image_results)} 张配图到 session_uid={session_uid}")
    
    # 持久化保存到本地文件
    if saved_count > 0:
        try:
            save_persistent_state()
            print("[配图保存] 持久化保存成功")
        except Exception as e:
            print(f"保存配图持久化失败: {e}")


def _save_knowledge_point_image(session_uid, image_result):
    """保存知识点配图到 session state（手动生成时调用）"""
    if 'kp_images'not in st.session_state:
        st.session_state['kp_images'] = {}

    if session_uid not in st.session_state['kp_images']:
        st.session_state['kp_images'][session_uid] = {}

    kp_name = image_result.get('knowledge_point_name', 'Unknown')
    st.session_state['kp_images'][session_uid][kp_name] = image_result
    
    # 持久化保存到本地文件
    try:
        save_persistent_state()
    except Exception as e:
        print(f"保存配图持久化失败: {e}")


def render_image_generator_modal(goal, learning_session, knowledge_points, image_type):
    """显示图像生成对话框"""
    session_uid = get_current_session_uid()

    # 使用container替代expander避免嵌套问题
    with st.container(border=True):
        # 添加关闭按钮
        col_close, col_title = st.columns([1, 10])
        with col_close:
            if st.button("", icon=":material/close:", key=f"close_modal_{session_uid}_{image_type}"):
                st.session_state['image_modal_open'] = None
                st.rerun()
        with col_title:
            st.markdown("###  图像生成设置")

        # 选择图像生成模式
        image_mode = st.selectbox(
            "图像生成方式",
            options=[
                ("search", "必应图片搜索（免费，无需配置）"),
                ("doubao", "豆包 AI 生成（需要配置 API Key）"),
            ],
            format_func=lambda x: x[1],
            key=f"image_mode_{session_uid}_{image_type}"
        )[0]
        
        if image_mode == "doubao":
            st.info("豆包 AI 可以生成高质量的定制图像，请确保已在后端配置 VOLCENGINE_API_KEY 环境变量")

        style = st.selectbox(
            "视觉风格",
            options=[
                ("educational", "教育风格"),
                ("cartoon", "卡通风格"),
                ("minimalist", "简约风格"),
                ("detailed", "详细风格"),
                ("infographic", "信息图表风格")
            ],
            format_func=lambda x: x[1],
            key=f"style_{session_uid}_{image_type}"
        )[0]

        size = st.selectbox(
            "图像尺寸",
            options=["1024x1024", "1792x1024", "1024x1792"],
            key=f"size_{session_uid}_{image_type}"
        )

        learning_content_description = _build_image_description(goal, learning_session, knowledge_points)

        with st.container(border=True):
            st.markdown("**图像描述:**")
            st.text(learning_content_description)

        if st.button("开始生成", key=f"generate_{session_uid}_{image_type}", type="primary"):
            with st.spinner("正在生成图像，请稍候..."):
                try:
                    result = generate_learning_image(
                        learning_content=learning_content_description,
                        image_type=image_type,
                        style=style,
                        size=size,
                        llm_type="gpt4o",
                        image_mode=image_mode
                    )

                    if result and result.get("success"):
                        if session_uid not in st.session_state['generated_images']:
                            st.session_state['generated_images'][session_uid] = []

                        image_info = {
                            "image_url": result.get("image_url"),
                            "image_type": image_type,
                            "style": style,
                            "prompt": result.get("prompt", "")
                        }
                        st.session_state['generated_images'][session_uid].append(image_info)
                        st.success("图像生成成功！")
                        st.rerun()
                    else:
                        error_msg = result.get('detail', '未知错误') if result else '无响应'
                        st.error(f"图像生成失败: {error_msg}")
                        if "VOLCENGINE_API_KEY"in str(error_msg):
                            st.info("请在 .env 文件中添加 VOLCENGINE_API_KEY=你的API密钥")
                except Exception as e:
                    st.error(f"生成图像时出错: {str(e)}")


def render_knowledge_graph_section(goal, learning_session):
    """渲染学习进度知识图谱

    显示一个线性的知识图谱，展示学习进度：
    - 灰色节点 = 未学习
    - 橙色节点 = 学习中
    - 绿色节点 = 已完成
    """
    session_uid = get_current_session_uid()

    # 初始化知识图谱数据
    if 'knowledge_graphs'not in st.session_state:
        st.session_state['knowledge_graphs'] = {}

    # 获取知识点数据
    knowledge_points = None
    if session_uid in st.session_state.get('document_caches', {}):
        # 从缓存中获取知识点
        doc_cache = st.session_state['document_caches'].get(session_uid, {})
        if isinstance(doc_cache, dict) and 'knowledge_points'in doc_cache:
            knowledge_points = doc_cache['knowledge_points']

    # 如果没有图谱数据，尝试生成
    if session_uid not in st.session_state['knowledge_graphs'] or not st.session_state['knowledge_graphs'][session_uid]:
        if knowledge_points:
            # 使用简单线性图谱（无需调用API）
            graph_data = create_simple_linear_graph(knowledge_points)
            st.session_state['knowledge_graphs'][session_uid] = graph_data
        # 缓存的 knowledge_points 缺失时不回退到全局变量（会串到其它环节），
        # 该环节图谱暂不生成，待其文档生成后自然可用

    # 显示知识图谱
    graph_data = st.session_state['knowledge_graphs'].get(session_uid)

    if graph_data and graph_data.get('nodes'):
        st.divider()
        st.subheader("学习进度知识图谱")

        # 计算进度
        nodes = graph_data.get('nodes', [])
        completed_count = sum(1 for n in nodes if n.get('status') == 'completed')
        total_count = len(nodes)
        progress_pct = int(completed_count / total_count * 100) if total_count > 0 else 0

        st.markdown(f"""
        <div class="gm-graph-info" style="margin-bottom:15px; font-size:14px;">
             学习进度: {completed_count}/{total_count} 个知识点已完成 ({progress_pct}%)
        </div>
        """, unsafe_allow_html=True)

        # 进度条
        st.progress(progress_pct / 100)

        # 渲染图谱
        render_knowledge_graph(graph_data, height=200)

        # 更新进度的按钮区域
        st.markdown("** 点击下方按钮标记知识点学习状态：**")

        # 所有节点统一显示，每行最多 4 个
        nodes_per_row = 4
        rows_needed = (len(nodes) + nodes_per_row - 1) // nodes_per_row
        for row_idx in range(rows_needed):
            row_start = row_idx * nodes_per_row
            row_end = min(row_start + nodes_per_row, len(nodes))
            row_nodes = nodes[row_start:row_end]
            cols = st.columns(len(row_nodes))
            for col_pos, (node, col) in enumerate(zip(row_nodes, cols)):
                actual_index = row_start + col_pos
                node_name = node.get('name', f'节点{actual_index+1}')
                status = node.get('status', 'unlearned')

                with col:
                    # 根据状态设置按钮样式和标签
                    if status == 'completed':
                        btn_type = "primary"
                        btn_label = node_name[:6]
                        btn_icon = ":material/check_circle:"
                    elif status == 'in_progress':
                        btn_type = "secondary"
                        btn_label = node_name[:6]
                        btn_icon = ":material/autorenew:"
                    else:
                        btn_type = "secondary"
                        btn_label = node_name[:6]
                        btn_icon = ":material/radio_button_unchecked:"

                    if st.button(
                        btn_label,
                        icon=btn_icon,
                        key=f"kp_node_{session_uid}_{actual_index}",
                        type=btn_type,
                        use_container_width=True,
                        help=f"{'点击标记为未学习'if status == 'completed'else '点击标记为已完成'}: {node_name}"
                    ):
                        # 切换状态：未学习/学习中 → 已完成；已完成 → 未学习
                        new_status = "completed"if status != "completed"else "unlearned"
                        st.session_state['knowledge_graphs'][session_uid]['nodes'][actual_index]['status'] = new_status
                        try:
                            save_persistent_state()
                        except Exception:
                            pass
                        st.rerun()

        st.divider()


def render_multimodal_image_generation(goal, learning_session, knowledge_points):
    """渲染多模态内容生成（图像生成）UI

    允许用户生成学习相关的可视化图像：
    - 知识树 (knowledge_tree)
    - 思维导图 (mind_map)
    - 概念图 (concept_diagram)
    - 学习路线图 (learning_roadmap)
    - 总结海报 (summary_poster)
    """
    st.subheader("多模态内容生成 - 图像")

    # 初始化 session state 用于存储生成的图像
    session_uid = get_current_session_uid()
    if 'generated_images'not in st.session_state:
        st.session_state['generated_images'] = {}

    # 选择图像类型
    image_type = st.selectbox(
        "选择图像类型",
        options=[
            ("mind_map", "思维导图"),
            ("knowledge_tree", "知识树"),
            ("concept_diagram", "概念图"),
            ("learning_roadmap", "学习路线图"),
            ("summary_poster", "总结海报")
        ],
        format_func=lambda x: x[1],
        key=f"image_type_{session_uid}"
    )[0]

    # 选择视觉风格
    style = st.selectbox(
        "选择视觉风格",
        options=[
            ("educational", "教育风格"),
            ("cartoon", "卡通风格"),
            ("minimalist", "简约风格"),
            ("detailed", "详细风格"),
            ("infographic", "信息图表风格")
        ],
        format_func=lambda x: x[1],
        key=f"image_style_{session_uid}"
    )[0]

    # 图像尺寸
    size = st.selectbox(
        "选择图像尺寸",
        options=["1024x1024", "1792x1024", "1024x1792"],
        key=f"image_size_{session_uid}"
    )

    # 构建学习内容描述
    learning_content_description = _build_image_description(goal, learning_session, knowledge_points)

    # 显示图像描述（使用 container 代替 expander 避免嵌套问题）
    with st.container(border=True):
        st.markdown("**图像描述预览:**")
        st.text(learning_content_description)

    st.divider()

    # 生成按钮
    col1, col2 = st.columns([1, 4])
    with col1:
        generate_button = st.button(
            "生成图像",
            key=f"generate_image_{session_uid}",
            use_container_width=True
        )

    if generate_button:
        with st.spinner("正在生成图像，请稍候..."):
            try:
                result = generate_learning_image(
                    learning_content=learning_content_description,
                    image_type=image_type,
                    style=style,
                    size=size,
                    llm_type="gpt4o"
                )

                if result and result.get("success"):
                    # 存储生成的图像
                    if session_uid not in st.session_state['generated_images']:
                        st.session_state['generated_images'][session_uid] = []

                    image_info = {
                        "image_url": result.get("image_url"),
                        "image_type": image_type,
                        "style": style,
                        "prompt": result.get("prompt", "")
                    }
                    st.session_state['generated_images'][session_uid].append(image_info)
                    st.success("图像生成成功！")
                else:
                    st.error(f"图像生成失败: {result.get('detail', '未知错误') if result else '无响应'}")

            except Exception as e:
                st.error(f"生成图像时出错: {str(e)}")

    # 显示已生成的图像
    if session_uid in st.session_state['generated_images']:
        images = st.session_state['generated_images'][session_uid]
        if images:
            st.divider()
            st.subheader("已生成的图像")

            for idx, img_info in enumerate(images):
                with st.container(border=True):
                    type_labels = {
                        "mind_map": "思维导图",
                        "knowledge_tree": "知识树",
                        "concept_diagram": "概念图",
                        "learning_roadmap": "学习路线图",
                        "summary_poster": "总结海报"
                    }
                    style_labels = {
                        "educational": "教育风格",
                        "cartoon": "卡通风格",
                        "minimalist": "简约风格",
                        "detailed": "详细风格",
                        "infographic": "信息图表风格"
                    }
                    type_name = type_labels.get(img_info['image_type'], img_info['image_type'])
                    style_name = style_labels.get(img_info['style'], img_info['style'])
                    st.markdown(f"**{idx + 1}. {type_name}**（{style_name}）")
                    st.image(_image_source(img_info['image_url']), use_container_width=True)

                    # 显示提示词（可选）
                    with st.expander("查看图像提示词"):
                        st.text(img_info['prompt'])

                    # 删除按钮
                    if st.button("删除", icon=":material/delete:", key=f"delete_img_{session_uid}_{idx}"):
                        st.session_state['generated_images'][session_uid].pop(idx)
                        st.rerun()


def _build_image_description(goal, learning_session, knowledge_points):
    """构建用于图像生成的学习内容描述"""
    # 提取学习目标
    learning_goal = goal.get("learning_goal", "学习内容")

    # 提取会话标题和摘要
    session_title = learning_session.get("title", "")
    session_abstract = learning_session.get("abstract", "")

    # 提取关联技能
    associated_skills = learning_session.get("associated_skills", [])

    # 构建描述文本
    description_parts = [
        f"学习主题: {learning_goal}",
        f"本次学习: {session_title}",
        f"内容摘要: {session_abstract}"
    ]

    if associated_skills:
        description_parts.append(f"关联技能: {', '.join(associated_skills)}")

    if knowledge_points:
        kp_names = [kp.get("name", "") for kp in knowledge_points if isinstance(kp, dict)]
        if kp_names:
            description_parts.append(f"关键知识点: {', '.join(kp_names[:5])}")

    return "\n".join(description_parts)


def _extract_section_kp_name(section_markdown: str) -> str | None:
    """从 section 内容中提取知识点名称（H3 标题）"""
    h3_matches = re.findall(r'^###\s+(.+)$', section_markdown, re.MULTILINE)
    if h3_matches:
        return h3_matches[0].strip()
    return None


def _find_matching_kp_image(session_uid: str, section_markdown: str) -> dict | None:
    """根据 section 内容找到匹配的知识点配图"""
    kp_images = st.session_state.get('kp_images', {}).get(session_uid, {})
    if not kp_images:
        return None

    # 策略1：直接匹配知识点名称（H3 标题）
    kp_name = _extract_section_kp_name(section_markdown)
    if kp_name:
        # 精确匹配
        if kp_name in kp_images:
            return kp_images[kp_name]
        # 模糊匹配（包含关系）
        for name, img in kp_images.items():
            if kp_name in name or name in kp_name:
                return img

    # 策略2：从 H2 标题提取关键词匹配
    h2_matches = re.findall(r'^##\s+(.+)$', section_markdown, re.MULTILINE)
    if h2_matches:
        section_title = h2_matches[0].strip().lower()
        for name, img in kp_images.items():
            if any(kw in section_title or section_title in kw for kw in [name.lower(), name.replace(' ', '').lower()]):
                return img

    return None


def _render_inline_kp_image(session_uid: str, section_markdown: str):
    """在段落后面渲染匹配的知识点配图"""
    img_info = _find_matching_kp_image(session_uid, section_markdown)
    if not img_info or not img_info.get('image_url'):
        return

    with st.container(border=True):
        col_text, col_img = st.columns([1, 2])
        with col_text:
            # 只展示知识点名称，不暴露"配图/风格"等内部元数据
            kp_name = img_info.get('knowledge_point_name', '')
            if kp_name:
                st.markdown(f"**{kp_name}**")

        with col_img:
            st.image(_image_source(img_info['image_url']), use_container_width=True)


def render_document_content_by_section(learning_content):
    selected_gid = st.session_state["selected_goal_id"]
    session_id = st.session_state["selected_session_id"]
    session_uid = get_current_session_uid()
    if "current_page"not in st.session_state or not isinstance(st.session_state["current_page"], dict):
        st.session_state["current_page"] = {}

    document = learning_content.get("document", "")
    titles = re.findall(r'^(#+)\s*(.*)', document, re.MULTILINE)

    section_starts = []
    start_idx = 0
    for title in titles:
        if title[0] == "#":
            continue
        elif title[0] == "##":
            start_idx = document.find(title[1], start_idx)
            section_starts.append(start_idx-3)
    section_documents = []
    for i in range(len(section_starts)):
        start_idx = section_starts[i]
        end_idx = section_starts[i + 1] if i + 1 < len(section_starts) else len(document)
        section_documents.append(document[start_idx:end_idx-1].strip())

    followup_rounds = ensure_followup_rounds_state(learning_content)
    base_page_count = len(section_documents)
    total_pages = base_page_count + len(followup_rounds)

    page_key = get_current_document_page_key()

    if total_pages == 0:
        st.warning("本文档没有可显示的章节。")
        st.session_state["if_render_qizzes"] = False
        st.session_state["active_followup_round_index"] = None
        return

    current_page = max(0, min(st.session_state['current_page'].get(page_key, 0), total_pages - 1))
    st.session_state['current_page'][page_key] = current_page

    # 记录当前页码
    st.session_state[f"{page_key}__prev"] = current_page

    st.session_state["active_followup_round_index"] = None
    if current_page < base_page_count:
        current_doc = section_documents[current_page]
        st.markdown(current_doc)

        # 自动嵌入匹配的知识点配图
        _render_inline_kp_image(session_uid, current_doc)

        st.session_state["if_render_qizzes"] = (current_page == base_page_count - 1)
    else:
        round_idx = current_page - base_page_count
        round_state = ensure_round_state(followup_rounds[round_idx])
        st.session_state["active_followup_round_index"] = round_idx + 1
        st.markdown(round_state.get("section_document") or "")
        st.session_state["if_render_qizzes"] = True

    st.sidebar.markdown('<div class="gm-toc-marker"></div>', unsafe_allow_html=True)
    st.sidebar.header("文档结构")
    curr_l2 = 0
    curr_l3 = 0
    page_idx_counter = -1
    for m in re.finditer(r'^(#+)\s*(.+)$', document, re.MULTILINE):
        level_marks, title_txt = m.group(1), m.group(2).strip()
        level_len = len(level_marks)
        if level_len == 1:
            continue
        if level_len == 2:
            page_idx_counter += 1
            curr_l2 += 1
            curr_l3 = 0
            if st.sidebar.button(f"{curr_l2}. {title_txt}", key=f"toc_l2_{page_idx_counter}", type="primary"if page_idx_counter == current_page else "secondary"):
                st.session_state.setdefault("current_page", {})[page_key] = page_idx_counter
                st.rerun()
            st.sidebar.markdown("")

        elif level_len == 3 and page_idx_counter >= 0:
            curr_l3 += 1
            st.sidebar.markdown(f"&nbsp;&nbsp;&nbsp;[{curr_l2}.{curr_l3}. {title_txt}](#{title_txt.lower().replace(' ', '-').replace('，','').replace('。','')})", unsafe_allow_html=True)

    if followup_rounds:
        st.sidebar.divider()
        for r_idx, round_state in enumerate(followup_rounds, start=1):
            page_idx = base_page_count + r_idx - 1
            mode_label = "模式A"if round_state.get("mode", "A") == "A"else "模式B"
            round_title = round_state.get("section_title") or f"补强轮次 {r_idx}"
            if st.sidebar.button(f"{mode_label} · {round_title}", key=f"toc_followup_{r_idx}", type="primary"if page_idx == current_page else "secondary"):
                st.session_state.setdefault("current_page", {})[page_key] = page_idx
                st.rerun()
            st.sidebar.markdown("")

    col_prev, col_center, col_next= st.columns([1, 4, 1])
    if current_page > 0:
        if col_prev.button("上一页", icon=":material/arrow_back:", use_container_width=True, key="prev-section-page"):
            new_page = current_page - 1
            st.session_state["current_page"][page_key] = new_page
            try:
                save_persistent_state()
            except Exception:
                pass
            st.rerun()
    if current_page < total_pages - 1:
        if col_next.button("下一页", icon=":material/arrow_forward:", use_container_width=True, key="next-section-page"):
            new_page = current_page + 1
            st.session_state["current_page"][page_key] = new_page
            try:
                save_persistent_state()
            except Exception:
                pass
            st.rerun()

    st.divider()

def render_document_content_by_document(document):
    st.session_state["if_render_qizzes"] = True

    titles = re.findall(r'^(#+)\s*(.*)', document, re.MULTILINE)

    sections = []
    for level, title in titles:
        section = {'level': len(level), 'title': title}
        sections.append(section)

    sidebar_content = ""
    curr_level_1_idx = 0
    curr_level_2_idx = 0
    curr_level_3_idx = 0
    for i, section in enumerate(sections):
        anchor = re.sub(r'[^\w\s]', '-', section["title"].lower()).replace(" ", "-")
        if section["level"] == 1:
            continue
        if section["level"] == 2:
            curr_level_2_idx += 1
            curr_level_3_idx = 0
            sidebar_content += f"[**{curr_level_2_idx}. {section['title']}**](#{anchor})\n"
        elif section["level"] == 3:
            curr_level_3_idx += 1
            sidebar_content += f"> [{curr_level_2_idx}.{curr_level_3_idx}. {section['title']}](#{anchor})\n\n"

    st.sidebar.markdown('<div class="gm-toc-marker"></div>', unsafe_allow_html=True)
    st.sidebar.header("文档结构")
    st.sidebar.markdown(sidebar_content)

    st.markdown(document)

    for section in sections:
        anchor = section["title"].replace(" ", "").replace("，", "").replace("。", "")
        st.markdown(f"<a name='{anchor}'></a>", unsafe_allow_html=True)


def render_questions(goal, round_state, quiz_data, session_information, round_key="session_round", round_label="Quiz"):
    """渲染当前轮次测验：逐题采集作答 → 全部提交后自动触发诊断与画像更新。"""
    quiz_entries = build_quiz_entries(quiz_data or {})
    if not quiz_entries:
        st.warning("本环节暂无测验题目。")
        return

    ensure_quiz_attempt_state(round_state, quiz_entries)

    session_uid = get_current_session_uid()
    any_question_submitted = False

    for index, entry in enumerate(quiz_entries, start=1):
        attempt = round_state["quiz_attempts"][entry["question_id"]]
        widget_prefix = f"{session_uid}_{round_key}_{entry['question_id']}"
        with st.container(border=True):
            st.write(f"**{index}. {entry['question']}**")

            if entry["question_type"] == "single_choice":
                stored_answer = attempt.get("user_answer")
                default_index = entry["options"].index(stored_answer) if stored_answer in entry["options"] else None
                selected_answer = st.radio(
                    "选项",
                    entry["options"],
                    key=f"{widget_prefix}_single_choice",
                    index=default_index,
                    label_visibility="hidden",
                )
            elif entry["question_type"] == "multiple_choice":
                selected_answer = []
                selected_set = set(attempt.get("user_answer") or [])
                for option_index, option in enumerate(entry["options"]):
                    if st.checkbox(option, key=f"{widget_prefix}_multiple_choice_{option_index}", value=option in selected_set):
                        selected_answer.append(option)
            elif entry["question_type"] == "true_false":
                stored_answer = attempt.get("user_answer")
                default_index = ["正确", "错误"].index(stored_answer) if stored_answer in ["正确", "错误"] else None
                selected_answer = st.radio(
                    "判断",
                    ["正确", "错误"],
                    key=f"{widget_prefix}_true_false",
                    index=default_index,
                    label_visibility="hidden",
                )
            else:
                selected_answer = st.text_input(
                    "你的答案",
                    key=f"{widget_prefix}_short_answer",
                    value=attempt.get("user_answer") or "",
                    label_visibility="hidden",
                )

            submit_label = "重新提交"if attempt.get("is_submitted") else "提交"
            if st.button(submit_label, key=f"{widget_prefix}_submit"):
                if entry["question_type"] in {"single_choice", "true_false"} and selected_answer is None:
                    st.warning("请先选择一个答案再提交。")
                elif entry["question_type"] == "multiple_choice"and not selected_answer:
                    st.warning("请至少选择一个选项再提交。")
                elif entry["question_type"] == "short_answer"and not str(selected_answer).strip():
                    st.warning("请先输入答案再提交。")
                else:
                    round_state["quiz_attempts"][entry["question_id"]] = build_attempt_payload(entry, selected_answer)
                    attempt = round_state["quiz_attempts"][entry["question_id"]]
                    any_question_submitted = True
                    try:
                        save_persistent_state()
                    except Exception:
                        pass

            if attempt.get("is_submitted"):
                if entry["question_type"] == "short_answer":
                    if attempt.get("is_correct") is True:
                        st.success("正确！")
                    elif attempt.get("is_correct") is False:
                        st.error("错误。")
                    else:
                        st.info("已提交，等待语义评估。")
                else:
                    if attempt.get("is_correct"):
                        st.success("正确！")
                    else:
                        st.error("错误。")

                with st.expander("解析", expanded=False, icon=":material/info:"):
                    st.write(entry.get("explanation") or "暂无解析。")

    # 全部提交后：触发 LLM 诊断 + 把结果写入学习者画像
    all_submitted = len(get_submitted_quiz_attempts(round_state, quiz_entries)) == len(quiz_entries)
    analysis_signature = compute_quiz_analysis_signature(round_state, quiz_entries) if all_submitted else None
    analysis_is_stale = all_submitted and (
        round_state.get("quiz_analysis_signature") != analysis_signature
        or (
            not round_state.get("quiz_analysis")
            and round_state.get("quiz_analysis_requested_signature") not in {analysis_signature, None}
        )
    )
    if all_submitted and (any_question_submitted or analysis_is_stale):
        refresh_quiz_analysis(goal, round_state, session_information, quiz_entries, force=True)

    profile_update_is_stale = all_submitted and round_state.get("quiz_profile_update_signature") != analysis_signature
    if all_submitted and round_state.get("quiz_analysis") and (any_question_submitted or analysis_is_stale or profile_update_is_stale):
        refresh_learner_profile_from_quiz(
            goal,
            round_state,
            session_information,
            quiz_entries,
            round_label,
            force=any_question_submitted or analysis_is_stale,
        )

    render_quiz_analysis(round_state, quiz_entries)

def render_content_feedback_form(goal, session_info=None):
    st.header("感谢您的反馈！")
    with st.form("feedback_form"):
        st.info("您的反馈将帮助我们改善学习体验。请花一点时间分享您的想法。")

        col1, col2 = st.columns([1, 3])
        col1.write("内容清晰度")
        clarity = col2.feedback("stars", key="clarity")

        col1, col2 = st.columns([1, 3])
        col1.write("目标相关性")
        relevance = col2.feedback("stars", key="relevance")

        col1, col2 = st.columns([1, 3])
        col1.write("内容深度")
        depth = col2.feedback("stars", key="depth")

        col1, col2 = st.columns([1, 3])
        col1.write("参与度")
        engagement = col2.feedback("faces", key="engagement")

        additional_comments = st.text_area("其他意见", max_chars=500)
        # 不使用 on_click+kwargs：回调在下一轮 rerun 开始时执行，携带的是"上一次渲染"的
        # 旧值，首次提交会把空反馈发给后端。改为在提交分支内读取本轮最新控件值。
        submitted = st.form_submit_button("提交反馈")
        if submitted:
            feedback_data = {
                "clarity": clarity,
                "relevance": relevance,
                "depth": depth,
                "engagement": engagement,
                "additional_comments": additional_comments,
            }
            update_learner_profile_with_feedback(goal, feedback_data, session_information=session_info)
            st.success("感谢您的反馈！")

def update_learner_profile_with_feedback(goal, feedback_data, session_information="", mark_session_learned=False, show_toast=True):
    """把交互反馈/测验结果交给后端 LLM 更新学习者画像。

    Args:
        goal: 学习目标对象
        feedback_data: 反馈数据（反馈表单内容或测验结果结构）
        session_information: 会话信息
        mark_session_learned: 是否在会话信息中标记 if_learned=True
        show_toast: 是否显示结果 toast 提示

    Returns:
        bool: 更新是否成功
    """
    if show_toast:
        st.toast("正在更新学习者画像...")
    if session_information != "":
        session_information = copy.deepcopy(session_information)
        if mark_session_learned:
            session_information["if_learned"] = True

    with st.spinner("正在更新学习者画像，请稍候..."):
        new_learner_profile = update_learner_profile(
            goal["learner_profile"],
            feedback_data,
            session_information=session_information
        )

    if new_learner_profile is None:
        if show_toast:
            st.error("更新学习者资料失败，请确保后端服务已启动。")
        return False
    else:
        goal["learner_profile"] = new_learner_profile
        if show_toast:
            st.toast("学习者画像已更新！")
        return True

def load_knowledge_point_content(file_path):
    try:
        knowledge_document = json.load(open(file_path, encoding='utf-8'))
        return knowledge_document
    except FileNotFoundError:
        st.error("未找到知识文档，请确保 `knowledge_document.md` 在正确的目录中。")
        return None

render_learning_content()