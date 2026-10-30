#!/usr/bin/env bash
# 兼容 macOS 自带的 Bash 3.2 与 Linux Bash。
set -euo pipefail

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
PYTHON="$PROJECT_DIR/frontend/.venv/bin/python"
DEPS_MARKER="$PROJECT_DIR/frontend/.venv/.deps_sh_checksum"

fail() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

is_python312() {
    "$1" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>/dev/null
}

if [[ ! -x "$PYTHON" ]]; then
    # 可以用 PYTHON_BIN 指定路径；始终按单个路径处理，不执行其中的 shell 文本。
    BASE_PYTHON="${PYTHON_BIN:-}"
    if [[ -n "$BASE_PYTHON" ]]; then
        is_python312 "$BASE_PYTHON" || fail 'PYTHON_BIN 必须指向 Python 3.12。'
    else
        for candidate in python3.12 python3 python; do
            if command -v "$candidate" >/dev/null 2>&1 && is_python312 "$candidate"; then
                BASE_PYTHON="$candidate"
                break
            fi
        done
    fi
    [[ -n "$BASE_PYTHON" ]] || fail '未找到 Python 3.12，请安装或设置 PYTHON_BIN。'
    printf '正在创建 frontend/.venv…\n'
    "$BASE_PYTHON" -m venv "$PROJECT_DIR/frontend/.venv"
fi
is_python312 "$PYTHON" || fail '现有 frontend/.venv 不是 Python 3.12，请先迁移该环境。'

if [[ ! -f backend/.env ]]; then
    cp backend/.env.example backend/.env
    fail '已创建 backend/.env，请填写 DEEPSEEK_API_KEY 后重新运行。'
fi

# 依赖清单变化或安装失败时，下次启动会重新安装。
DEPS_CHECKSUM="$(cksum backend/requirements.txt frontend/requirements.txt)"
if [[ ! -f "$DEPS_MARKER" ]] || [[ "$(cat "$DEPS_MARKER")" != "$DEPS_CHECKSUM" ]]; then
    printf '正在安装前后端依赖（首次可能需要较长时间）…\n'
    "$PYTHON" -m pip install -r backend/requirements.txt -r frontend/requirements.txt
    printf '%s\n' "$DEPS_CHECKSUM" > "$DEPS_MARKER"
fi

# 使用项目已有的 dotenv 解析器，不把配置文件当作 shell 脚本执行。
"$PYTHON" -c 'from dotenv import dotenv_values; import sys; sys.exit(0 if (dotenv_values("backend/.env").get("DEEPSEEK_API_KEY") or "").strip() else 1)' \
    || fail 'backend/.env 中的 DEEPSEEK_API_KEY 为空或无法读取。'

# 提前发现端口冲突，避免只启动一半服务。
"$PYTHON" -c '
import socket
import sys
for port in (5000, 8501):
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    except OSError:
        sys.exit(f"端口 {port} 无法绑定，请检查是否已被占用。")
'

BACKEND_PID=''
FRONTEND_PID=''
cleanup() {
    trap - EXIT INT TERM
    for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
        if [[ -n "$pid" ]]; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
        if [[ -n "$pid" ]]; then
            wait "$pid" 2>/dev/null || true
        fi
    done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

(
    cd "$PROJECT_DIR/backend"
    exec "$PYTHON" -m uvicorn main:app --host 127.0.0.1 --port 5000
) &
BACKEND_PID=$!
(
    cd "$PROJECT_DIR/frontend"
    exec "$PYTHON" -m streamlit run main.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
) &
FRONTEND_PID=$!

printf '正在启动服务，就绪后请打开 http://localhost:8501\n按 Ctrl+C 停止前后端，日志显示在当前终端。\n'
# 不使用 macOS 自带 Bash 不支持的 wait -n。
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 1
done
fail '前端或后端已退出，请查看上方日志；另一服务将自动停止。'
