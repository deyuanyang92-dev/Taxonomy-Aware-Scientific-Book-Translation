#!/usr/bin/env bash
# 把仓库里的技能文件同步到技能目录（仓库为准，技能目录只是副本）。
#
# 复制范围：skill/*.md、skill/*.tsv、skill/domains/、scripts/（不含 __pycache__）。
# 技能目录里仓库没有的文件（terms/、备份目录等）不动、不删，只在最后列出。
#
# 用法：
#   scripts/sync_skill.sh            # 先打印差异，再复制
#   scripts/sync_skill.sh --dry      # 只打印差异，不复制
#   SKILL_DIR=/其他/路径 scripts/sync_skill.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${SKILL_DIR:-$HOME/.claude/skills/yzz-translate}"
DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

mkdir -p "$DEST"
changed=0

# 源文件列表（相对路径 -> 源路径）：skill/*.md、skill/domains/*、scripts/ 下全部文件
list_sources() {
    (cd "$REPO/skill" && find . -maxdepth 1 \( -name '*.md' -o -name '*.tsv' \) -type f | sed 's|^\./||')
    (cd "$REPO/skill" && find domains -type f)
    (cd "$REPO" && find scripts -type f ! -path '*/__pycache__/*' ! -name '*.pyc')
}

# skill/ 下的文件落在技能目录根，scripts/ 下的保持 scripts/ 前缀
src_of() {
    case "$1" in
        scripts/*) echo "$REPO/$1" ;;
        *) echo "$REPO/skill/$1" ;;
    esac
}

SOURCES="$(list_sources | sort)"

while IFS= read -r rel; do
    src="$(src_of "$rel")"
    dst="$DEST/$rel"
    if [ ! -e "$dst" ]; then
        echo "新增  $rel"
        changed=$((changed + 1))
    elif ! cmp -s "$src" "$dst"; then
        echo "更新  $rel"
        diff -u --label "技能目录/$rel" --label "仓库/$rel" "$dst" "$src" | sed 's/^/    /' | head -40 || true
        changed=$((changed + 1))
    else
        continue
    fi
    if [ "$DRY" -eq 0 ]; then
        mkdir -p "$(dirname "$dst")"
        cp -p "$src" "$dst"
    fi
done <<< "$SOURCES"

# 技能目录里有、仓库里没有的文件：只提示
extra=0
while IFS= read -r rel; do
    case "$rel" in
        terms/*|_backup*|*/__pycache__/*|*.pyc) continue ;;
    esac
    if ! grep -qxF "$rel" <<< "$SOURCES"; then
        [ "$extra" -eq 0 ] && echo "仅技能目录有（未动，请确认是否应并入仓库）："
        echo "    $rel"
        extra=$((extra + 1))
    fi
done < <(cd "$DEST" && find . -type f ! -path './terms/*' ! -path './_backup*' ! -path '*/__pycache__/*' | sed 's|^\./||' | sort)

if [ "$changed" -eq 0 ]; then
    echo "技能目录已与仓库一致：$DEST"
elif [ "$DRY" -eq 1 ]; then
    echo "（--dry）共 $changed 个文件有差异，未复制"
else
    echo "已同步 $changed 个文件到 $DEST"
fi
