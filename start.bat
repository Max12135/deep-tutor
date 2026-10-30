@echo off
setlocal enabledelayedexpansion
title DeepTutor
cd /d "%~dp0"

set "VENV=frontend\.venv"
set "PYEXE=%VENV%\Scripts\python.exe"

echo ==========================================
echo    DeepTutor 一键启动
echo ==========================================
echo.

REM ---------- 1) 准备虚拟环境 ----------
if exist "%PYEXE%" (
    echo [1/4] 已检测到虚拟环境，跳过创建。
    goto :deps
)

echo [1/4] 首次运行：正在创建虚拟环境（frontend\.venv）...

REM 依次尝试：手动指定文件 > py 启动器 > PATH 上的 python > 常见安装位置
REM 统一解析成 python.exe 的完整路径，最后再校验是不是 3.12
set "CAND="
if exist "python_path.txt" for /f "usebackq delims=" %%x in ("python_path.txt") do if not defined CAND if exist "%%~x" set "CAND=%%~x"
if not defined CAND for /f "delims=" %%x in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "CAND=%%~x"
if not defined CAND for /f "delims=" %%x in ('python3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "CAND=%%~x"
if not defined CAND for /f "delims=" %%x in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "CAND=%%~x"
if not defined CAND for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "C:\Python312\python.exe"
    "C:\ProgramData\anaconda3\python.exe"
    "C:\ProgramData\miniconda3\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
) do if not defined CAND if exist "%%~p" set "CAND=%%~p"

REM 校验必须是 3.12（用退出码判断，避免解析版本字符串）
set "BASEPY="
if defined CAND "%CAND%" -c "import sys;sys.exit(0 if sys.version_info[:2]==(3,12) else 1)"
if defined CAND if not errorlevel 1 set "BASEPY=%CAND%"

if not defined BASEPY (
    echo.
    echo [错误] 没有找到 Python 3.12。
    echo.
    echo   办法一：装一个 Python 3.12
    echo     https://www.python.org/downloads/release/python-3129/
    echo     安装时务必勾选 "Add python.exe to PATH"，装好后重新双击本文件。
    echo.
    echo   办法二：如果你已经装过 3.12（比如 Anaconda 的某个环境里），
    echo     把那个 python.exe 的完整路径写进本目录下的 python_path.txt，例如：
    echo       D:\Python312\python.exe
    echo     保存后再双击本文件。
    echo.
    pause
    exit /b 1
)
echo       使用解释器：!BASEPY!
"!BASEPY!" -m venv "%VENV%"
if errorlevel 1 (
    echo [错误] 创建虚拟环境失败。
    pause
    exit /b 1
)

:deps
REM ---------- 2) 安装依赖 ----------
if exist "%VENV%\.deps_ok" (
    echo [2/4] 依赖已安装，跳过。（要重装就删掉 frontend\.venv\.deps_ok）
    goto :env
)
echo [2/4] 安装依赖（首次很慢，约需数百 MB 下载，请保持联网）...
"%PYEXE%" -m pip install --upgrade pip || goto :pipfail
"%PYEXE%" -m pip install -r backend\requirements.txt || goto :pipfail
"%PYEXE%" -m pip install -r frontend\requirements.txt || goto :pipfail
type nul > "%VENV%\.deps_ok"
goto :env

:pipfail
echo.
echo [错误] 依赖安装失败，请检查网络后重试（重跑本文件即可续装）。
pause
exit /b 1

:env
REM ---------- 3) 准备 .env ----------
if exist "backend\.env" (
    echo [3/4] backend\.env 已存在，跳过。
) else (
    copy /y "backend\.env.example" "backend\.env" >nul
    echo [3/4] 已生成 backend\.env，即将打开记事本。
    echo       请在 DEEPSEEK_API_KEY= 后面填入你的 Key，保存并关闭记事本。
    notepad "backend\.env"
)

REM 校验 DEEPSEEK_API_KEY 是否已填写，避免起一个注定报错的服务
set "DSKEY="
for /f "usebackq tokens=1,* delims==" %%a in ("backend\.env") do (
    if /i "%%a"=="DEEPSEEK_API_KEY" set "DSKEY=%%b"
)
REM 去掉首尾空格；仍为空则视为未填写
if defined DSKEY set "DSKEY=!DSKEY: =!"
if not defined DSKEY (
    echo.
    echo [错误] backend\.env 里的 DEEPSEEK_API_KEY 还是空的。
    echo   请打开 backend\.env，在 DEEPSEEK_API_KEY= 后面填入你的 Key 再重新运行本文件。
    echo   申请地址：https://platform.deepseek.com/
    echo.
    pause
    exit /b 1
)

REM ---------- 4) 启动前后端 ----------
echo [4/4] 启动后端与前端...
start "DeepTutor-后端(5000)" cmd /k "cd backend && ..\frontend\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 5000"
start "DeepTutor-前端(8501)" cmd /k "cd frontend && .venv\Scripts\python.exe -m streamlit run main.py"

echo       等待前端就绪（首次可能要多等一会儿）...
powershell -NoProfile -Command "for($i=0;$i -lt 80;$i++){try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',8501);$c.Close();exit 0}catch{Start-Sleep -Milliseconds 1500}};exit 1"

if errorlevel 1 (
    echo.
    echo [警告] 前端在等待时间内没有就绪，未自动打开浏览器。
    echo   请查看上面两个黑窗口里的报错信息；若稍后自己就绪，可手动打开 http://localhost:8501
    echo.
) else (
    echo       正在打开浏览器 http://localhost:8501
    start "" "http://localhost:8501"
)

echo.
echo 完成。关闭那两个黑窗口即可停止服务。
echo 本窗口 10 秒后自动关闭。
timeout /t 10 >nul
exit /b 0
