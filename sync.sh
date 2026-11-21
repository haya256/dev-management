#!/usr/bin/env bash
# スキャン → commit → 他PCの最新を取得 → index.md 再生成 → push をまとめて行う
# 使い方: ./sync.sh [scan.py のオプション（例: --skip-env）]
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d data/.git ]; then
    echo "data/ がありません。README.md の初回セットアップ手順で data/ をクローンしてください。" >&2
    exit 1
fi

# Windows（Git Bash）の python3 は Microsoft Store を開くだけの仮のコマンドのことがあるので、動く方を使う
if python3 -c "" >/dev/null 2>&1; then
    PY=python3
elif python -c "" >/dev/null 2>&1; then
    PY=python
else
    echo "Python が見つかりません（python3 / python）。" >&2
    exit 1
fi
# Windows の Python でもファイルの読み書きを UTF-8 にする
export PYTHONUTF8=1

# 環境名（config/host.conf の HOST_NAME。無ければホスト名）。scan.py と同じ決め方にする
host="$("$PY" scan.py --print-host)"

# 各ステップの所要時間を記録し、最後にまとめて表示する
# （macOS 標準の bash 3.2 でも動くよう、秒単位の SECONDS を使う）
summary=""
step_name=""
step_start=0
step() {
    end_step
    step_name="$1"
    step_start=$SECONDS
    echo "==> $1"
}
end_step() {
    if [ -n "$step_name" ]; then
        summary="${summary}  ${step_name}: $((SECONDS - step_start)) 秒"$'\n'
    fi
}

step "スキャン"
"$PY" scan.py "$@"

# pull --rebase は未コミットの変更があると失敗するため、先に commit する
step "commit"
git -C data add pc-data/
if git -C data diff --cached --quiet; then
    echo "変更なし"
else
    git -C data commit -q -m "scan: ${host} $(date +%Y-%m-%d)"
fi

step "他PCの最新を取得"
git -C data pull -q --rebase origin main
"$PY" scan.py --merge-only

step "push"
if [ -n "$(git -C data log origin/main..HEAD --oneline)" ]; then
    git -C data push -q origin main
else
    echo "push するものなし"
fi

end_step
echo
echo "所要時間（合計 ${SECONDS} 秒）"
printf "%s" "$summary"
echo "完了: data/index.md の「PC環境」を確認してください"
