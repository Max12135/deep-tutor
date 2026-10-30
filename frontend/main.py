import streamlit as st
import time
import os
from pathlib import Path

# 无论从哪个目录启动，都统一切换到 frontend 目录，保证相对路径可用
try:
    os.chdir(Path(__file__).resolve().parent)
except Exception:
    pass

from utils.state import initialize_session_state, change_selected_goal_id, save_persistent_state, load_persistent_state, _get_data_store_path
initialize_session_state()


st.session_state.setdefault("_autosave_enabled", True)
try:
    save_persistent_state()
except Exception:
    pass

from components.chatbot import render_chatbot

st.set_page_config(page_title="DeepTutor", page_icon=str(Path(__file__).parent / "assets" / "logo_favicon.png"), layout="wide")
try:
    _logo_path = Path(__file__).parent / "assets" / "logo_header.png"
    if _logo_path.exists():
        st.logo(str(_logo_path))
except Exception:
    pass

# 加载自定义 CSS（使用绝对路径 + 容错读取，避免编码或路径问题）
try:
    _css_path = Path(__file__).parent / "assets" / "css" / "main.css"
    _css_text = _css_path.read_text(encoding="utf-8")
    st.markdown("<style>" + _css_text + "</style>", unsafe_allow_html=True)
except Exception as _css_err:
    st.warning(f"自定义样式加载失败（不影响功能）：{_css_err}")

# 本地数据读写异常提示：加载失败每次会话提示一次；保存失败也只提示一次，避免刷屏
_persist_load_notice = st.session_state.pop("_persist_load_notice", None)
if _persist_load_notice:
    st.warning(_persist_load_notice)
_persist_load_err = st.session_state.pop("_persist_load_error", None)
if _persist_load_err:
    st.error(_persist_load_err)
_persist_save_err = st.session_state.get("_persist_save_error")
if _persist_save_err and not st.session_state.get("_persist_save_error_shown"):
    st.session_state["_persist_save_error_shown"] = True
    st.warning(_persist_save_err)

try:
    if st.session_state.get("if_complete_onboarding", False) and not st.session_state.get("_navigated_lp_once", False):
        st.session_state["_navigated_lp_once"] = True
        try:
            st.switch_page("app_pages/learning_path.py")
        except Exception:
            pass
except Exception:
    pass

@st.dialog("确认重置")
def show_reset_dialog():
    st.warning("确定要清除所有历史记录吗？此操作不可撤销。")
    st.divider()
    col_confirm, _space, col_cancel = st.columns([1, 2, 0.7])
    with col_confirm:
        if st.button("确认", type="primary"):
            from pathlib import Path
            from datetime import datetime
            import shutil
            try:
                st.session_state["_autosave_enabled"] = False
            except Exception:
                pass
            try:
                data_path = _get_data_store_path()
            except Exception:
                data_path = Path(__file__).resolve().parent / "user_data" / "data_store.json"
            try:
                data_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            if data_path.exists():
                try:
                    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                    backup_path = data_path.parent / f"data_storage-{ts}.json"
                    shutil.copy2(str(data_path), str(backup_path))
                except Exception:
                    pass
                try:
                    data_path.unlink()
                except Exception:
                    pass
            try:
                st.session_state.clear()
            except Exception:
                pass
            try:
                # 清除状态后，显式导航到引导页面
                try:
                    st.switch_page("app_pages/onboarding.py")
                except Exception:
                    st.rerun()
            except Exception:
                try:
                    st.rerun()
                except Exception:
                    pass
    with col_cancel:
        if st.button("取消"):
            # simply rerun to close the dialog without changes
            try:
                st.rerun()
            except Exception:
                try:
                    st.rerun()
                except Exception:
                    pass

# 学习分析
_PAGES_DIR = str((Path(__file__).resolve().parent / "app_pages"))

if st.session_state["if_complete_onboarding"]:
    onboarding = st.Page(f"{_PAGES_DIR}/onboarding.py", title="入门引导", icon=":material/how_to_reg:", default=False, url_path="onboarding")
    learning_path = st.Page(f"{_PAGES_DIR}/learning_path.py", title="学习路径", icon=":material/route:", default=True, url_path="learning_path")
else:
    onboarding = st.Page(f"{_PAGES_DIR}/onboarding.py", title="入门引导", icon=":material/how_to_reg:", default=True, url_path="onboarding")
    learning_path = st.Page(f"{_PAGES_DIR}/learning_path.py", title="学习路径", icon=":material/route:", default=False, url_path="learning_path")
skill_gaps = st.Page(f"{_PAGES_DIR}/skill_gap.py", title="技能差距", icon=":material/insights:", default=False, url_path="skill_gap")
knowledge_document = st.Page(f"{_PAGES_DIR}/knowledge_document.py", title="继续学习", icon=":material/menu_book:", default=False, url_path="knowledge_document")
learner_profile = st.Page(f"{_PAGES_DIR}/learner_profile.py", title="我的资料", icon=":material/person:", default=False, url_path="learner_profile")
goal_management = st.Page(f"{_PAGES_DIR}/goal_management.py", title="目标管理", icon=":material/flag:", default=False, url_path="goal_management")
dashboard = st.Page(f"{_PAGES_DIR}/dashboard.py", title="学习分析", icon=":material/browse:", default=False, url_path="dashboard")

# Learning Analytics Dashboard
if not st.session_state["if_complete_onboarding"]:
    nav_position = "sidebar"
    pg = st.navigation({"DeepTutor": [onboarding, skill_gaps, learning_path]}, position="hidden", expanded=True)
else:
    nav_position = "sidebar"
    pg = st.navigation({"DeepTutor": [goal_management, learning_path, knowledge_document, learner_profile, dashboard]}, position=nav_position, expanded=True)
    with st.sidebar:
        if st.button("重置数据", icon=":material/restart_alt:", help="清除全部本地学习记录（目标、画像、聊天记录等），清除前会自动备份为带时间戳的文件", use_container_width=True):
            show_reset_dialog()
        # 询问导师入口（原右下角悬浮按钮已移除，改放侧边栏）
        if st.session_state["show_chatbot"]:
            st.divider()
            render_chatbot()
    goal = st.session_state["goals"][st.session_state["selected_goal_id"]]
    # 仅在缺失时初始化 start_time（持久化），不要每次 rerun 重置，
    # 否则下面的 600s 采样分支永远进不去，掌握度趋势会退化为单点
    if not goal.get('start_time'):
        goal['start_time'] = time.time()
    try:
        save_persistent_state()
    except Exception:
        pass
    # 画像可能尚未就绪（为空字典或 None）。此处必须防御性取值，
    # 否则直接下标访问画像字段会 TypeError，导致应用每次打开都崩、重启无效。
    _cognitive = (goal.get('learner_profile') or {}).get('cognitive_status') or {}
    unlearned_skill = len(_cognitive.get('in_progress_skills') or [])
    learned_skill = len(_cognitive.get('mastered_skills') or [])
    all_skill = learned_skill + unlearned_skill

    # 历史键统一用字符串：经 JSON 持久化后对象键必然是字符串，
    # 若此处用 int 键会在跨重启后匹配失败，导致趋势被空列表覆盖。
    gid = str(goal['id'])
    if gid not in st.session_state['learned_skills_history']:
        st.session_state['learned_skills_history'][gid] = []
        try:
            save_persistent_state()
        except Exception:
            pass

    if all_skill != 0:
        mastery_rate = learned_skill / all_skill if all_skill != 0 else 0
        if st.session_state['learned_skills_history'][gid] == []:
            st.session_state['learned_skills_history'][gid].append(mastery_rate)
            try:
                save_persistent_state()
            except Exception:
                pass
    if all_skill != 0 and (time.time() - goal['start_time'] > 600):
        goal['start_time'] = time.time()
        try:
            save_persistent_state()
        except Exception:
            pass
        st.session_state['learned_skills_history'][gid].append(mastery_rate)
        try:
            save_persistent_state()
        except Exception:
            pass

    if len(st.session_state['learned_skills_history'][gid]) > 10:
        st.session_state['learned_skills_history'][gid].pop(0)
        try:
            save_persistent_state()
        except Exception:
            pass

    try:
        save_persistent_state()
    except Exception:
        pass

try:
    if st.session_state.get("_autosave_enabled", True):
        save_persistent_state()
except Exception:
    pass

if len(st.session_state["goals"]) != 0:
    change_selected_goal_id(st.session_state["selected_goal_id"])
    try:
        save_persistent_state()
    except Exception:
        pass

# 侧边栏激活项高亮（Reader 式砖橙实底；通过同源 iframe 脚本给当前页链接加类）
try:
    import streamlit.components.v1 as _components
    _nav_js = r"""
<script>
(function(){
  var doc = window.parent.document;
  var NAV = '[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]';

  // 统一的一次「重标」：Streamlit 的软导航（SPA）与局部重渲染都会重建侧栏 DOM，
  // 只跑一次会漏（类会被抹掉、内联样式会丢），所以每轮都重新查询、重新施加，
  // 由 MutationObserver + 轻量轮询驱动，保证任何时刻状态都正确。
  function tick(){
    // 1) 激活项：当前页对应的导航项加 .gm-active（Reader 式砖橙实底）
    var path = (window.parent.location.pathname || '/').replace(/^\//, '');
    doc.querySelectorAll(NAV).forEach(function(a){
      var href = (a.getAttribute('href') || '').replace(window.parent.location.origin + '/', '').replace(/^\//, '');
      var isActive = (href === path) || (path === '' && href === 'learning_path');
      if (a.classList.contains('gm-active') !== isActive) {
        a.classList.toggle('gm-active', isActive);
      }
    });

    var sidebar = doc.querySelector('section[data-testid="stSidebar"]');
    var collapsed = !!sidebar && sidebar.getAttribute('aria-expanded') === 'false';

    // 2) 品牌 logo：行内样式直达，规避样式表级联竞争
    var logo = doc.querySelector('img[data-testid="stLogo"]');
    if (logo) {
      var s = logo.style;
      s.setProperty('margin', '0', 'important');
      s.setProperty('padding', '0', 'important');
      s.setProperty('height', '34px', 'important');
      s.setProperty('width', 'auto', 'important');
      s.setProperty('max-height', 'none', 'important');
      s.setProperty('max-width', 'none', 'important');
      s.setProperty('object-fit', 'contain', 'important');
      // 收起态（图标栏）隐藏 logo
      s.setProperty('display', collapsed ? 'none' : 'block', 'important');
    }

    // 3) 折叠按钮：暖底方块；收起态放大到 44×44，与图标格同规格；展开态还原 34×34
    var collapse = doc.querySelector('[data-testid="stSidebarCollapseButton"]');
    var innerBtn = collapse ? collapse.querySelector('button') : null;
    if (collapse) {
      collapse.style.setProperty('display', 'block', 'important');
    }
    if (innerBtn) {
      var t = innerBtn.style;
      t.setProperty('display', 'flex', 'important');
      t.setProperty('align-items', 'center', 'important');
      t.setProperty('justify-content', 'center', 'important');
      t.setProperty('background', 'var(--gray-tint)', 'important');
      t.setProperty('border-radius', '10px', 'important');
      t.setProperty('padding', '0', 'important');
      t.setProperty('margin', '0', 'important');
      t.setProperty('width', collapsed ? '44px' : '34px', 'important');
      t.setProperty('height', collapsed ? '44px' : '34px', 'important');
    }

    // 4) 运行时对齐：把 logo 中线平移到折叠按钮中线（偏差收敛后不再重复施加）
    if (logo && innerBtn) {
      var lb = logo.getBoundingClientRect();
      var bb = innerBtn.getBoundingClientRect();
      if (lb.height > 0 && bb.height > 0) {
        var delta = (bb.top + bb.height / 2) - (lb.top + lb.height / 2);
        if (Math.abs(delta) > 0.5) {
          var cur = parseFloat(logo.style.marginTop) || 0;
          logo.style.setProperty('margin-top', (cur + delta).toFixed(1) + 'px', 'important');
        }
      }
    }
  }

  tick();
  try {
    new MutationObserver(tick).observe(doc.body, {
      subtree: true, childList: true, attributes: true,
      attributeFilter: ['class', 'href', 'aria-expanded']
    });
  } catch (e) {}
  setInterval(tick, 400);
  setTimeout(tick, 300);
})();
</script>
"""
    _components.html(_nav_js, height=0)
except Exception:
    pass

pg.run()

