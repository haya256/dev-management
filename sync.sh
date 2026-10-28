#!/usr/bin/env bash
# スキャン → commit → 他PCの最新を取得 → index.md 再生成 → push をまとめて行う
# 使い方: ./sync.sh [scan.py のオプション（例: --skip-env）]
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d data/.git ]; then
    echo "data/ がありません。README.md の初回セットアップ手順で data/ をクローンしてください。" >&2
    exit 1
fi

host="$(scutil --get LocalHostName 2>/dev/null || hostname)"

echo "==> スキャン"
python3 scan.py "$@"

# pull --rebase は未コミットの変更があると失敗するため、先に commit する
echo "==> commit"
git -C data add pc-data/
if git -C data diff --cached --quiet; then
    echo "変更なし"
else
    git -C data commit -q -m "scan: ${host} $(date +%Y-%m-%d)"
fi

echo "==> 他PCの最新を取得"
git -C data pull -q --rebase origin main
python3 scan.py --merge-only

echo "==> push"
if [ -n "$(git -C data log origin/main..HEAD --oneline)" ]; then
    git -C data push -q origin main
else
    echo "push するものなし"
fi

echo "完了: data/index.md の「PC環境」を確認してください"
