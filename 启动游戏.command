#!/bin/bash
# 双击这个文件启动《AI 中转站》。
# 游戏起来之后，这个黑色终端窗口会立刻自己关掉（游戏在后台独立运行）。
# 如果没能启动，窗口会留着显示日志。
cd "$(dirname "$0")" || exit 1

MY_TTY=$(tty 2>/dev/null)
LOG="$PWD/启动日志.txt"

CANDIDATES=(
  "/Users/zhangjiazheng/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
  "$(command -v python3)"
  "/opt/homebrew/bin/python3"
  "/usr/local/bin/python3"
  "/usr/bin/python3"
)

PY=""
for p in "${CANDIDATES[@]}"; do
  [ -n "$p" ] && [ -x "$p" ] || continue
  if "$p" -c "import pygame" >/dev/null 2>&1; then
    PY="$p"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "没找到装了 pygame 的 python3。"
  echo "在终端里跑一句就好：  python3 -m pip install pygame"
  read -r -p "按回车关闭..." _
  exit 0
fi

# 脱离终端跑：这样关掉窗口不会把游戏一起带走
nohup "$PY" game.py >"$LOG" 2>&1 &
GAME_PID=$!

# 等一下，确认它真的起来了（导入失败会立刻退出）
sleep 1.2
if ! kill -0 "$GAME_PID" 2>/dev/null; then
  echo "游戏没能启动，日志如下："
  echo "----------------------------------------"
  tail -n 20 "$LOG" 2>/dev/null
  echo "----------------------------------------"
  read -r -p "按回车关闭..." _
  exit 0
fi

# 起来了：把这个终端窗口关掉（延迟一点，让 shell 先退干净）
case "$MY_TTY" in
  /dev/*)
    ( sleep 0.3; osascript \
        -e "tell application \"Terminal\" to close (every window whose tty is \"$MY_TTY\")" \
        >/dev/null 2>&1 ) >/dev/null 2>&1 &
    ;;
esac
exit 0
