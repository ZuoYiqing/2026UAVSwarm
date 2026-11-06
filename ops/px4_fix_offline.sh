#!/usr/bin/env bash
# px4_fix_offline.sh —— 让从 tar 包解出来的 PX4 源码树能在完全离线环境里编译
#
# 为什么需要这个脚本（四处检查，全部实测确认）
# --------------------------------------------
# 离线包为了省 1.6 GB 没有打包 .git。PX4 构建链上有四处因此失败：
#
#   ①  Makefile:38-40
#         ifeq ($(wildcard .git),)
#             $(error YOU HAVE TO USE GIT TO DOWNLOAD THIS REPOSITORY. ABORTING.)
#         endif
#       → 根目录没 .git 直接中止
#
#   ②  cmake/px4_git.cmake:58  px4_add_git_submodule()
#         add_custom_command(... DEPENDS ${PX4_SOURCE_DIR}/.gitmodules ${PATH}/.git)
#       → 子模块目录没 .git，ninja 报：
#         ninja: error: 'src/drivers/gps/devices/.git', needed by
#         'src/drivers/gps/git_init_devices.stamp', missing and no known rule to make it
#
#   ③  src/lib/version/px_update_git_header.py:80
#         subprocess.check_output('git rev-parse --verify HEAD'.split())
#       → 根仓库没有有效 HEAD 时报 CalledProcessError exit 128
#
#   ④  同文件 :118-121 和 :128-134
#         if os.path.exists('src/modules/mavlink/mavlink/.git'):
#             subprocess.check_output('git rev-parse --verify HEAD'... cwd=那个子模块)
#         if os.path.exists('platforms/nuttx/NuttX/nuttx/.git'):
#             ... git tag ... + git rev-parse --verify HEAD ...
#       → **光有 .git 文件不够，那必须是"真仓库且 HEAD 有效"**，
#         否则判断为真却执行 git 失败，同样报 128
#
# 关键结论：**子模块的 .git 不能是假占位文件，必须是能 git rev-parse 的微型真仓库。**
#
# PX4 还自带一个离线开关（Tools/check_submodules.sh:39-42）：
#     [ -n "$GIT_SUBMODULES_ARE_EVIL" ] && { exit 0 }
# 设了就跳过子模块联网更新。
#
# 本脚本做的事
# ------------
#   ① 根仓库:  git init + 空提交（秒级，只要有效 HEAD，不占空间）
#   ② 每个子模块: 同样建一个微型真仓库（git init + 空提交，每个约 160 KB）
#   ③ 自检:    跑一遍 px_update_git_header.py，确认第 ③④ 关能过
#   ④ 打印带 GIT_SUBMODULES_ARE_EVIL=1 的编译命令
#
# 用法
# ----
#   cd ~/PX4-Autopilot
#   bash px4_fix_offline.sh                  # 只修
#   bash px4_fix_offline.sh --build          # 修完直接编 gz_x500_mono_cam
#   bash px4_fix_offline.sh --build none     # 修完只编 SITL 核心（快）
#
set -u

BUILD_TARGET=""; DO_BUILD=0
if [ "${1:-}" = "--build" ]; then
  DO_BUILD=1
  BUILD_TARGET="${2:-gz_x500_mono_cam}"
  [ "$BUILD_TARGET" = "none" ] && BUILD_TARGET=""
fi

if [ ! -f Makefile ] || [ ! -f .gitmodules ]; then
  echo "❌ 当前目录不是 PX4 源码根目录（找不到 Makefile / .gitmodules）"
  echo "   先 cd 过去：cd ~/PX4-Autopilot"
  exit 1
fi
ROOT=$(pwd)
echo "PX4 源码根目录: $ROOT"
echo

G="git -c user.email=offline@local -c user.name=offline"

# ---------- ① 根仓库 ----------
echo "① 根仓库（过 Makefile:38 与 py:80）"
if [ ! -d .git ]; then
  git init -q . || { echo "   ❌ git init 失败（装了 git 吗？）"; exit 1; }
  echo "   git init 完成"
fi
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "   ✅ HEAD 有效: $(git rev-parse --short HEAD)"
else
  # 注意：绝对不要把这行接到 | head 之类的管道上，SIGPIPE 会打断 git 导致提交对象写不完
  if $G commit --allow-empty -q -m "offline tarball baseline" 2>/tmp/px4_fix_root.err; then
    echo "   ✅ 已建空提交: $(git rev-parse --short HEAD)"
  else
    echo "   ❌ 空提交失败："
    head -5 /tmp/px4_fix_root.err | sed 's/^/      /'
    exit 1
  fi
fi

# ---------- ② 每个子模块 ----------
echo
echo "② 每个子模块建微型真仓库（过 cmake:58 与 py:118/128）"
ok=0; bad=0
while IFS= read -r p; do
  [ -z "$p" ] && continue
  if [ ! -d "$p" ]; then
    printf '   ⚠️  目录不存在，跳过: %s\n' "$p"; continue
  fi
  if (
      cd "$p" || exit 1
      # 假占位文件要清掉，否则 git 会把父仓库当 gitdir
      if [ -f .git ]; then rm -f .git; fi
      git init -q . 2>/dev/null || exit 1
      $G commit --allow-empty -q -m "offline submodule baseline" 2>/dev/null || exit 1
      git rev-parse --verify HEAD >/dev/null 2>&1 || exit 1
  ); then
    ok=$((ok+1))
  else
    bad=$((bad+1)); printf '   ❌ 失败: %s\n' "$p"
  fi
done < <(grep -E '^[[:space:]]*path[[:space:]]*=' .gitmodules | sed 's/.*=[[:space:]]*//')
echo "   成功 $ok 个 / 失败 $bad 个"

# ---------- ③ 自检 ----------
echo
echo "③ 自检：px_update_git_header.py（第 ③④ 关）"
SELFTEST=$(mktemp)
if python3 src/lib/version/px_update_git_header.py "$SELFTEST" --validate --git_tag 'v0.0.0' \
     >/tmp/px4_fix_hdr.log 2>&1; then
  echo "   ✅ 通过"
  grep -E 'GIT_VERSION_STR|GIT_TAG_STR' "$SELFTEST" 2>/dev/null | head -6 | sed 's/^/      /'
  rm -f "$SELFTEST"
else
  echo "   ❌ 仍然失败："
  head -10 /tmp/px4_fix_hdr.log | sed 's/^/      /'
  rm -f "$SELFTEST"
  echo "     → 若报 mavlink/nuttx 的 rev-parse，说明②里那个子模块没建好"
  exit 1
fi

# ---------- 抽查子模块内容 ----------
echo
echo "   抽查子模块内容（确认不是空目录）"
badcontent=0
for p in src/drivers/gps/devices src/modules/mavlink/mavlink Tools/simulation/gz \
         src/lib/events/libevents src/lib/crypto/libtomcrypt platforms/nuttx/NuttX/nuttx; do
  [ -d "$p" ] || continue
  n=$(find "$p" -type f -not -path '*/.git/*' 2>/dev/null | wc -l)
  if [ "$n" -gt 0 ]; then
    printf '      ✅ %-40s %6s 文件\n' "$p" "$n"
  else
    printf '      ❌ %-40s 空目录（源码缺失！）\n' "$p"; badcontent=$((badcontent+1))
  fi
done
[ "$badcontent" -gt 0 ] && echo "      ⚠️ 有 $badcontent 个子模块没源码，本脚本修不了，需要重新打包"

# ---------- ④ 编译命令 ----------
echo
echo "======================================================================"
echo " 修复完成。编译必须带 GIT_SUBMODULES_ARE_EVIL=1"
echo "======================================================================"
echo
echo "   先验证（只编核心，快）："
echo "     GIT_SUBMODULES_ARE_EVIL=1 make px4_sitl"
echo
echo "   再编仿真要用的相机机型："
echo "     GIT_SUBMODULES_ARE_EVIL=1 make px4_sitl gz_x500_mono_cam"
echo
echo "   不想每次都带环境变量的话，可以一次性把检查脚本变空操作："
echo "     printf '#!/bin/sh\\nexit 0\\n' > Tools/check_submodules.sh"
echo "   （效果相同，会改动 PX4 自带脚本）"
echo

if [ "$DO_BUILD" = "1" ]; then
  echo "======================================================================"
  echo " 开始编译: make px4_sitl $BUILD_TARGET"
  echo "======================================================================"
  rm -rf build
  export GIT_SUBMODULES_ARE_EVIL=1
  if [ -z "$BUILD_TARGET" ]; then make px4_sitl; else make px4_sitl "$BUILD_TARGET"; fi
fi
