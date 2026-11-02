@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI 中转站

rem 依次尝试几种常见的 Python 启动方式（Windows 上可能叫 py / python / python3）
set "PY="
for %%P in (py python python3) do (
  if not defined PY (
    %%P -c "import sys" >nul 2>&1 && set "PY=%%P"
  )
)

if not defined PY (
  echo 没找到 Python。请先安装 Python 3.10+：https://www.python.org/downloads/
  echo 安装时记得勾选 "Add Python to PATH"。
  pause
  exit /b 1
)

rem 检查 pygame，没有就提示安装命令
%PY% -c "import pygame" >nul 2>&1
if errorlevel 1 (
  echo 还差一个依赖 pygame，正在尝试自动安装...
  %PY% -m pip install pygame
  %PY% -c "import pygame" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo 自动安装失败，请手动执行：  %PY% -m pip install pygame
    pause
    exit /b 1
  )
)

%PY% game.py
if errorlevel 1 (
  echo.
  echo 游戏异常退出，上面是错误信息。
  pause
)
