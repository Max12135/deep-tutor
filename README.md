# DeepTutor · 使用说明

一个「目标导向」的 AI 学习助手：你输入一个学习目标（例如"学习线性代数"），它自动识别技能差距 → 生成学习路径 → 逐环节生成中英文学习文档与配图 → 出测验并自动判分 → 根据薄弱点补强，循环推进；全程有 AI 导师随时答疑。

- 前端：Streamlit（`frontend/`）
- 后端：FastAPI（`backend/`）
- 大模型：DeepSeek

---

## 一、环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10/11 ／ macOS ／ Linux |
| Python | **3.12**（不要用 3.13） |
| 网络 | 需要联网（首次安装要下载依赖与嵌入模型） |
| API Key | 一个自己的 **DeepSeek API Key**（付费，[申请地址](https://platform.deepseek.com/)） |

---

## 二、安装（只需做一次）

> **Windows 用户**：可以直接跳到 [三、启动](#三启动) 双击 `start.bat`，它会自动完成下面这些步骤，不用手敲命令。
> **macOS / Linux 用户**：可以直接使用第三节的 `./start.sh` 自动准备环境；也可按下面步骤手动安装。

在项目根目录（即本 README 所在目录）打开终端：

**Windows（PowerShell / CMD）**

```bat
python -m venv frontend\.venv
frontend\.venv\Scripts\activate
pip install -r backend\requirements.txt
pip install -r frontend\requirements.txt
copy backend\.env.example backend\.env
notepad backend\.env
```

**macOS / Linux**

```bash
python3.12 -m venv frontend/.venv
source frontend/.venv/bin/activate
pip install -r backend/requirements.txt
pip install -r frontend/requirements.txt
cp backend/.env.example backend/.env
nano backend/.env
```

最后一步会打开 `.env`，把

```
DEEPSEEK_API_KEY=
```

改成

```
DEEPSEEK_API_KEY=sk-你自己的key
```

保存即可。（`VOLCENGINE_API_KEY` 是可选的，只有想让学习内容里生成配图时才需要填。）

> ⏳ 首次安装比较慢：依赖里有 langchain / chroma / sentence-transformers，安装包体量较大；第一次运行时还会额外下载多语嵌入模型 `paraphrase-multilingual-MiniLM-L12-v2`（约 470MB）。请耐心等待并保持联网。

---

## 三、启动

### 方式一：一键启动（推荐，Windows）

**双击根目录下的 `start.bat`** 即可，它会自动完成：

1. 找 Python 3.12 → 创建 `frontend\.venv`（首次）
2. 安装前后端依赖（首次，较慢，需联网）
3. 若 `backend\.env` 不存在，自动复制模板并打开记事本让你填 Key
4. 分别启动**后端(5000)** 和**前端(8501)** 两个窗口
5. 等前端就绪后自动打开浏览器 http://localhost:8501

停止服务：关掉那两个黑窗口。

> 在 VS Code 里也可以 `Ctrl+Shift+B`（或 `终端 → 运行任务`）选 **“DeepTutor: 一键启动（后端+前端）”**，效果相同。
> 也可以只用 🐍 解释器手动跑：见方式三。

### 方式二：一键启动（macOS / Linux）

安装 Python 3.12 后，在项目根目录运行：

```bash
./start.sh
```

脚本自动创建 `frontend/.venv`。首次会复制 `backend/.env.example` 为 `backend/.env` 并退出，填写其中的 `DEEPSEEK_API_KEY` 后再次运行即可。脚本会安装前后端依赖，并在依赖清单变化时重新安装；安装标记位于虚拟环境内。

如需指定 Python 3.12 的位置：

```bash
PYTHON_BIN=/完整路径/python3.12 ./start.sh
```

前后端日志显示在同一个终端，服务就绪后打开 **http://localhost:8501**。按 **Ctrl+C** 同时停止两个服务；任一服务退出时，脚本也会停止另一个服务。端口固定为 5000 和 8501，仅监听本机。脚本可从其他目录通过完整路径调用。

### 方式三：手动启动（或想自己控制端口）

需要开**两个**终端窗口，都保持运行。

**终端 A —— 启动后端（先启动它）**

```bat
cd backend
..\frontend\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 5000
```

macOS / Linux：

```bash
cd backend
../frontend/.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 5000
```

看到 `Application startup complete.` 即成功。

**终端 B —— 启动前端**

```bat
cd frontend
.venv\Scripts\python.exe -m streamlit run main.py
```

macOS / Linux：

```bash
cd frontend
.venv/bin/python -m streamlit run main.py
```

浏览器打开 **http://localhost:8501** 即可。

---

## 四、第一次使用怎么走

1. **入门引导**：填写你的学习目标 + 简单背景（可选上传 PDF 简历、可填学习偏好）。
2. **技能差距**：系统会列出该目标涉及的技能，并标出你已有的 / 待补的，确认后点「安排学习路径」。
3. 之后自动进入 **学习路径** 页，逐个环节点「开始学习」。
4. **继续学习** 页里有正文、知识图谱、配图（配了豆包 Key 才有）和测验；做完测验会自动诊断薄弱点并给出补强内容。
5. 左侧栏 **AI 学习助手** 可随时提问，它会结合你的画像和进度回答。

### 页面一览

| 页面 | 作用 |
|---|---|
| 入门引导 | 首次进入，设置目标与个人背景 |
| 技能差距 | 查看/确认目标所需技能与差距 |
| 学习路径 | 学习环节列表与整体进度 |
| 继续学习 | 学习正文、知识图谱、配图、测验闭环 |
| 我的资料 | 查看与维护学习者画像 |
| 学习分析 | 掌握度趋势、雷达图等 |
| 目标管理 | 新增 / 编辑 / 删除 / 切换学习目标 |
| AI 学习助手 | 侧栏对话式答疑 |

---

## 五、常见问题

**Q：前端能打开，但一提问就提示"导师暂时无法回复"。**
后端没启动，或 `.env` 里的 `DEEPSEEK_API_KEY` 没填对。先确认终端 A 还在运行、并且 `.env` 已保存。

**Q：点「添加目标」后一直转圈很久。**
正常。生成学习路径 / 内容需要调用大模型，单次可能几十秒到几分钟。若长时间无响应，检查网络与 DeepSeek 余额。

**Q：端口被占用（8501 或 5000 已被使用）。**
换端口启动，例如后端 `--port 5001`；前端 `-m streamlit run main.py --server.port 8502`。
注意：如果改了后端端口，要同步修改 `frontend/config.py` 里的 `backend_endpoint`。

**Q：双击 `start.bat` 提示「没有找到 Python 3.12」。**
说明脚本没在常见位置找到 3.12（比如你机器上默认的 `python` 是 3.13/3.14）。两个办法：
① 按提示到 python.org 装一个 Python 3.12（勾选 Add to PATH）；
② 如果你**已经**装过 3.12（例如在某个 Anaconda 环境里），在项目根目录新建一个文本文件 `python_path.txt`，里面只写那一行 python.exe 的完整路径，例如 `D:\Python312\python.exe`（或 `D:\tools\Anaconda\envs\robot\python.exe`），保存后再双击 `start.bat`。

**Q：双击 `start.bat` 后要等很久。**
首次运行要在线安装 langchain / chroma / sentence-transformers（含 PyTorch，几百 MB 到 2 GB），装完会在 `frontend\.venv\.deps_ok` 留下标记，之后启动就是秒开。

**Q：学习内容里没有配图。**
配图走火山引擎豆包，需要在 `.env` 里填 `VOLCENGINE_API_KEY`；不填不影响其它功能。

**Q：想清空所有记录重新开始。**
侧栏底部「重置数据」按钮，会在 `frontend/user_data/` 下自动备份一份带时间戳的 json 后再清空。

**Q：我的数据存在哪？**
`frontend/user_data/data_store.json`（目标、画像、聊天记录、进度都在这里）。删除它相当于全部重置。

---

## 六、目录结构

```
DeepTutor/
├── backend/                    FastAPI 后端
│   ├── main.py                 接口入口
│   ├── api_schemas.py          请求 / 响应模型
│   ├── base/                   LLM、RAG、搜索、嵌入模型工厂
│   ├── config/                 Hydra 配置（default.yaml / main.yaml）
│   ├── modules/                各智能体模块
│   │   ├── skill_gap_identification/      技能差距识别
│   │   ├── adaptive_learner_modeling/     学习画像建模
│   │   ├── personalized_resource_delivery/ 路径规划 · 内容生成 · 测验闭环
│   │   └── ai_chatbot_tutor/              AI 导师
│   ├── data/vectorstore/       Chroma 向量库（RAG 资料索引）
│   ├── requirements.txt
│   └── .env.example            配置模板（复制成 .env 后填 Key）
├── frontend/                   Streamlit 前端
│   ├── main.py                 应用入口 / 侧栏 / 导航
│   ├── app_pages/              各页面
│   ├── components/             可复用 UI 组件
│   ├── utils/                  状态管理、后端请求封装
│   ├── assets/                 样式表、Logo、示例数据
│   ├── .streamlit/config.toml  主题与端口配置
│   ├── user_data/              本地数据（运行后生成，可删）
│   └── requirements.txt
├── .vscode/                    VS Code 任务配置（Ctrl+Shift+B 一键启动）
├── start.bat                   Windows 一键启动脚本
├── start.sh                    macOS / Linux 一键启动脚本
├── .gitignore
├── LICENSE
└── README.md
```

---

## 七、说明

- 本项目在开源工作 [GenMentor](https://github.com/GeminiLight/gen-mentor)（WWW 2025 Industry Track）基础上做二次开发：中文化、暖纸主题 UI 改版、以及移植队友的「测验 → 诊断 → 补强」学习闭环。原项目授权见 `LICENSE`。
- 后端与前端必须同时运行；前端只是界面，所有内容都由后端调用大模型生成。
