import streamlit as st
from collections import defaultdict
import config
import json
import os
from pathlib import Path

PERSIST_KEYS = [
    "backend_endpoint",
    "available_models",
    "if_complete_onboarding",
    "sample_number",
    "logged_in",
    "show_chatbot",
    "llm_type",
    "tutor_messages",
    "goals",
    "learner_information",
    "learner_information_pdf",
    "learner_information_text",
    "learner_occupation",
    # 注意：if_refining_learning_goal / if_rescheduling_learning_path / if_updating_learner_profile
    # 是"操作进行中"的瞬时标志，不能持久化——否则优化中途关闭页面后，下次启动会自动触发 LLM 调用。
    # 它们在 initialize_session_state() 中初始化为 False 即可。
    "selected_goal_id",
    "selected_session_id",
    "selected_point_id",
    "to_add_goal",
    "learned_skills_history",
    "userId",
    "document_caches",
    "session_learning_times",
    # 多模态功能持久化
    "knowledge_graphs",   # 知识串图谱节点状态（每个知识点的完成情况）
    "kp_images",          # 知识点配图缓存
    "generated_images",   # 已生成的结构图（思维导图等）
]


def _get_data_store_path():
    return Path(__file__).resolve().parents[1] / "user_data" / "data_store.json"


def _newest_backup_data(data_path):
    """在 user_data 目录里找最新的、可解析且非空的备份文件。

    返回 (data, backup_name)；找不到可用备份时返回 None。
    """
    try:
        candidates = list(data_path.parent.glob("data_storage-*.json"))
    except Exception:
        return None

    def _mtime(p):
        try:
            return p.stat().st_mtime
        except Exception:
            return 0.0

    for cand in sorted(candidates, key=_mtime, reverse=True):
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except Exception:
            continue
        # 只接受非空字典，避免"恢复"成一份同样无内容的备份
        if isinstance(data, dict) and data:
            return data, cand.name
    return None


def _preserve_corrupt_file(data_path) -> None:
    """把损坏的 data_store.json 另存一份，避免随后被自动回存覆盖而永久丢失。"""
    try:
        if st.session_state.get("_persist_corrupt_preserved"):
            return
        from datetime import datetime
        import shutil

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(str(data_path), str(data_path.parent / f"data_store-corrupt-{ts}.json"))
        st.session_state["_persist_corrupt_preserved"] = True
    except Exception:
        pass


def load_persistent_state():
    """Load persisted keys from a local JSON file into st.session_state.

    Only keys listed in PERSIST_KEYS will be restored.
    """
    path = _get_data_store_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        # 主入口加载后会立即回存（main.py 里的 save_persistent_state），若不处理，
        # 损坏内容会被空状态覆盖、数据永久丢失。故先尝试从最新备份自动恢复。
        restored = _newest_backup_data(path)
        if restored is not None:
            data, backup_name = restored
            try:
                st.session_state["_persist_load_notice"] = (
                    f"本地数据文件读取失败（{type(e).__name__}），已自动从最新备份"
                    f"「{backup_name}」恢复。"
                )
            except Exception:
                pass
        else:
            # 没有可用备份：先把损坏文件另存一份再继续，避免随后自动回存覆盖原内容。
            _preserve_corrupt_file(path)
            try:
                st.session_state["_persist_load_error"] = (
                    f"本地数据文件读取失败（{type(e).__name__}），且未找到可用备份，"
                    f"本次已跳过加载，界面将显示为空。损坏文件已另存备查。"
                )
            except Exception:
                pass
            return False
    for k, v in data.items():
        if k in PERSIST_KEYS:
            st.session_state[k] = v
    return True


def save_persistent_state():
    """Save whitelisted st.session_state keys to a local JSON file."""
    path = _get_data_store_path()
    data = {}
    for k in PERSIST_KEYS:
        if k in st.session_state:
            try:
                data[k] = st.session_state[k]
            except Exception:
                pass
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(data, ensure_ascii=False, indent=2)
        # 原子写：先写临时文件再替换，避免写入中途崩溃损坏 data_store.json 导致数据全失
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(serialized, encoding="utf-8")
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        # 记录失败原因，由主入口节流提示一次，避免保存静默失败导致进度悄悄丢失
        try:
            st.session_state["_persist_save_error"] = f"本地数据保存失败（{type(e).__name__}）：{e}"
        except Exception:
            pass
        return False


def initialize_session_state():
    for key in ["if_complete_onboarding", "is_learner_profile_ready", "is_learning_path_ready", "is_skill_gap_ready", "is_knowledge_document_ready"]:
        if key not in st.session_state:
            st.session_state[key] = False

    if "backend_endpoint" not in st.session_state:
        st.session_state["backend_endpoint"] = config.backend_endpoint

    if "available_models" not in st.session_state:
        st.session_state["available_models"] = ["OpenAI/GPT-4o"]

    if "llm_type" not in st.session_state:
        if len(st.session_state["available_models"]) > 0:
            st.session_state["llm_type"] = st.session_state["available_models"][0]
        else:
            st.session_state["llm_type"] = "None"

    if "userId" not in st.session_state:
        st.session_state["userId"] = "TestUser"
        
    if "sample_number" not in st.session_state:
        st.session_state["sample_number"] = 2
        
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if "show_chatbot" not in st.session_state:
        st.session_state["show_chatbot"] = True

    if "tutor_messages" not in st.session_state:
        st.session_state["tutor_messages"] = []

    if "selected_page" not in st.session_state:
        st.session_state["selected_page"] = "Onboarding"

    if "goals" not in st.session_state:
        st.session_state["goals"] = []
    
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = {}
        
    if "document_caches" not in st.session_state:
        st.session_state["document_caches"] = {}

    if "session_learning_times" not in st.session_state:
        st.session_state["session_learning_times"] = {}

    for key in ["learner_information", "learner_information_pdf", "learner_information_text", "learner_occupation"]:
        if key not in st.session_state:
            st.session_state[key] = ""

    if "if_refining_learning_goal" not in st.session_state:
        st.session_state["if_refining_learning_goal"] = False

    if "if_rescheduling_learning_path" not in st.session_state:
        st.session_state["if_rescheduling_learning_path"] = False

    if "if_updating_learner_profile" not in st.session_state:
        st.session_state["if_updating_learner_profile"] = False

    for key in ["selected_goal_id", "selected_session_id", "selected_point_id"]:
        if key not in st.session_state:
            st.session_state[key] = 0

    if "to_add_goal" not in st.session_state:
        reset_to_add_goal()

    if 'learned_skills_history' not in st.session_state:
        st.session_state['learned_skills_history'] = {}

    # 多模态功能状态初始化 - 先尝试加载持久化数据
    try:
        load_persistent_state()
    except Exception:
        pass

    # 如果加载后仍然是空的，则初始化为空字典
    if 'knowledge_graphs' not in st.session_state:
        st.session_state['knowledge_graphs'] = {}

    if 'kp_images' not in st.session_state:
        st.session_state['kp_images'] = {}

    if 'generated_images' not in st.session_state:
        st.session_state['generated_images'] = {}

def get_new_goal_uid():
    return max(goal["id"] for goal in st.session_state.goals) + 1 if st.session_state.goals else 0

def reset_to_add_goal():
    st.session_state["to_add_goal"] = {
        "learning_goal": "",
        "skill_gaps": [],
        "learner_profile": {},
        "learning_path": [],
        "is_completed": False,
        "is_deleted": False
    }
    return st.session_state["to_add_goal"]


def index_goal_by_id(goal_id):
    goal_id_list = [goal["id"] for goal in st.session_state["goals"]]
    try:
        return goal_id_list.index(goal_id)
    except ValueError:
        return None

def change_selected_goal_id(new_goal_id):
    if new_goal_id == st.session_state["selected_goal_id"]:
        return
    goals = st.session_state["goals"]
    st.session_state["selected_goal_id"] = new_goal_id
    goal_id_list = [goal["id"] for goal in goals]
    goal_id_idx = goal_id_list.index(new_goal_id)
    st.session_state["learning_goal"] = goals[goal_id_idx]["learning_goal"]
    st.session_state["learner_profile"] = goals[goal_id_idx]["learner_profile"]
    st.session_state["skill_gaps"] = goals[goal_id_idx]["skill_gaps"]
    st.session_state["learning_path"] = goals[goal_id_idx]["learning_path"]
    st.session_state["selected_session_id"] = 0
    st.session_state["selected_point_id"] = 0
    # status
    st.session_state["is_learner_profile_ready"] = True if st.session_state["learner_profile"] else False
    st.session_state["is_learning_path_ready"] = True if st.session_state["learning_path"] else False
    st.session_state["is_skill_gap_ready"] = True if st.session_state["skill_gaps"] else False
    # persist change
    try:
        save_persistent_state()
    except Exception:
        pass

def get_existing_goal_id_list():
    return [goal["id"] for goal in st.session_state["goals"]]

def add_new_goal(learning_goal="", skill_gaps=[], learner_profile={}, learning_path=[], is_completed=False, is_deleted=False):
    goal_uid = get_new_goal_uid()
    goal_info = {
        "id": goal_uid,
        "learning_goal": learning_goal,
        "skill_gaps": skill_gaps,
        "learner_profile": learner_profile,
        "learning_path": learning_path,
        "is_completed": is_completed,
        "is_deleted": is_deleted
    }
    st.session_state.goals.append(goal_info)
    goal_idx = index_goal_by_id(goal_uid)
    reset_to_add_goal()
    # persist after adding a goal
    try:
        save_persistent_state()
    except Exception:
        pass
    return goal_idx

def get_current_knowledge_point_uid():
    selected_gid = st.session_state["selected_goal_id"]
    selected_sid = st.session_state["selected_session_id"]
    selected_pid = st.session_state["selected_point_id"]
    return f"{selected_gid}-{selected_sid}-{selected_pid}"

def get_current_session_uid():
    selected_gid = st.session_state["selected_goal_id"]
    selected_sid = st.session_state["selected_session_id"]
    return f"{selected_gid}-{selected_sid}"
