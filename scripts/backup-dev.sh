#!/usr/bin/env bash
# ~/dev のバックアップ
#   使い方:  bash backup-dev.sh            → 差分コピー (rsync)
#            bash backup-dev.sh tar        → 1ファイルに固めて保存 (tar.gz)
#            bash backup-dev.sh check      → 未コミット/未push のリポジトリ確認だけ
#
# バックアップ先は PC ごとに違うため、このファイルには書かない。
#   config/backup.conf に  BACKUP_DEST=/path/to/backup  と書く（環境変数 BACKUP_DEST でも可）。
#   特定のパスを除外したいときは、同じファイルに BACKUP_EXCLUDE_PATHS=( "project/dir" ... ) と書く（~/dev からの相対パス）。
#   BACKUP_DEST は「保存先フォルダ」（この中に dev/ や tar ができる）。ドライブ直下や、名前が dev のフォルダは避ける。
#     rsync → $BACKUP_DEST/dev/   tar → $BACKUP_DEST/dev-日付.tar.gz
#   BACKUP_DEST は事前に作っておくこと（未接続のドライブに偽のバックアップ先を作らないため、自動では作らない）。
#   rsync は --delete を使うため、$BACKUP_DEST/dev/ に目印ファイル(.dev-backup)が無い限り、
#   中身のある既存フォルダには書き込まない（無関係なファイルを消さないため）。
# 詳細は docs/backup.md を参照。
set -euo pipefail

SRC="$HOME/dev"
MODE="${1:-rsync}"

# ~/dev/ からのシンボリックリンク経由で実行されても、本体の場所から config/ を探す
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
REPO_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
CONF="$REPO_DIR/config/backup.conf"

# 設定ファイルを読む。BACKUP_DEST は環境変数が指定されていればそれを優先する
ENV_DEST="${BACKUP_DEST:-}"
BACKUP_EXCLUDE_PATHS=()
if [ -f "$CONF" ]; then
  # shellcheck disable=SC1090
  . "$CONF"
fi
DEST="${ENV_DEST:-${BACKUP_DEST:-}}"

if [ ! -d "$SRC" ]; then
  echo "エラー: バックアップ元ディレクトリ '$SRC' が存在しません。" >&2
  exit 1
fi

# check モードはバックアップ先を使わない
if [ "$MODE" != "check" ]; then
  if [ -z "$DEST" ]; then
    echo "エラー: バックアップ先が未設定です。" >&2
    echo "  $CONF に BACKUP_DEST=/path/to/backup と書くか、環境変数 BACKUP_DEST を指定してください。" >&2
    exit 1
  fi
  if [ ! -d "$DEST" ]; then
    echo "エラー: バックアップ先 '$DEST' が存在しません。" >&2
    echo "  外付けドライブが接続・マウントされているか確認してください。" >&2
    echo "  初回は、先にこのフォルダを手動で作成してください（自動では作りません）。" >&2
    exit 1
  fi
fi

# 再生成できるので除外するディレクトリ
EXCLUDES=(
  node_modules .venv venv __pycache__ .pytest_cache .mypy_cache
  dist build .next .nuxt .cache .parcel-cache target .gradle .turbo
  certs
)

# config/backup.conf の BACKUP_EXCLUDE_PATHS で指定した、決め打ちのパス（~/dev からの相対パス）を除外する。
# 例: BACKUP_EXCLUDE_PATHS=( "some-project/videos" "other/secret.txt" )
# ~/dev/ や $HOME/dev/ から書いてもよい（取り除いて扱う）。
EXCLUDE_PATHS=()
for p in ${BACKUP_EXCLUDE_PATHS[@]+"${BACKUP_EXCLUDE_PATHS[@]}"}; do
  p="${p#"$HOME/dev/"}"
  p="${p#\~/dev/}"
  p="${p#/}"
  p="${p%/}"
  if [ -z "$p" ]; then
    continue
  fi
  case "/$p/" in
    */../*|*/./*)
      echo "エラー: BACKUP_EXCLUDE_PATHS に '..' や '.' を含むパスは書けません: '$p'" >&2
      exit 1 ;;
  esac
  if [ ! -e "$SRC/$p" ] && [ ! -L "$SRC/$p" ]; then
    echo "注意: 除外指定のパス '~/dev/$p' は存在しません（書き間違いでないか確認してください）。"
  fi
  EXCLUDE_PATHS+=("$p")
done
if [ "${#EXCLUDE_PATHS[@]}" -gt 0 ]; then
  echo "== 設定で除外するパス (config/backup.conf) =="
  printf '  ~/dev/%s\n' ${EXCLUDE_PATHS[@]+"${EXCLUDE_PATHS[@]}"}
  echo
fi

# ---- 1. 各 git リポジトリの未コミット / 未push を確認 -------------------
echo "== git 状態チェック (未コミット or 未push があるものだけ表示) =="
find "$SRC" -maxdepth 3 -type d -name .git -print0 2>/dev/null | sort -z | while IFS= read -r -d '' g; do
  repo="${g%/.git}"
  # 壊れたリポジトリで git が失敗しても set -e でループが落ちないよう || true
  dirty=$(git -C "$repo" status --porcelain 2>/dev/null | wc -l || true)
  # リモート追跡ブランチがない場合は "?"
  ahead=$(git -C "$repo" rev-list --count "@{u}..HEAD" 2>/dev/null || echo "?")
  if [ "$dirty" -ne 0 ] || [ "$ahead" != "0" ]; then
    printf "  %-50s 未コミット:%s 未push:%s\n" "${repo#"$SRC"/}" "$dirty" "$ahead"
  fi
done
echo "  (未push が ? のものはリモート未設定 = GitHub にバックアップされていない)"
echo
if [ "$MODE" = "check" ]; then
  exit 0
fi

# ---- 2. バックアップ本体 ----------------------------------------------------
args=()
for e in "${EXCLUDES[@]}"; do
  args+=(--exclude="$e")
done
# 決め打ちのパスは、rsync と tar で書き方が違う
#   rsync: 先頭の / で「~/dev 直下からのパス」に固定する
#   tar:   アーカイブ内の名前は dev/ から始まるので、dev/ を付ける。
#          GNU tar の --exclude は既定で先頭に固定されない（別の場所の同名パスまで除外する）ため、
#          --anchored で固定し、後ろの名前だけの除外（EXCLUDES）のために --no-anchored で戻す。
#          macOS の tar（bsdtar）には --anchored が無いので、固定されないまま使う（docs/backup.md 参照）
rsync_path_args=()
tar_path_args=()
for p in ${EXCLUDE_PATHS[@]+"${EXCLUDE_PATHS[@]}"}; do
  rsync_path_args+=(--exclude="/$p")
  tar_path_args+=(--exclude="dev/$p")
done
if [ "${#tar_path_args[@]}" -gt 0 ] && tar --version 2>/dev/null | grep -q 'GNU tar'; then
  tar_path_args=(--anchored "${tar_path_args[@]}" --no-anchored)
fi

# 実行結果を logs/backup.log（git 管理外）に 1 行追記する。rsync / tar の実行時だけ。
# 書式: 日時 モード 結果 所要秒数 保存先
LOG="$REPO_DIR/logs/backup.log"
result="成功"
started=0
start_log() {
  started=$SECONDS
  # trap は関数の外（スクリプト終了時）に動くので、started はグローバル変数にしてある
  trap '
    rc=$?
    [ "$rc" -ne 0 ] && result="失敗(rc=$rc)"
    mkdir -p "$(dirname "$LOG")"
    printf "%s %s %s %s秒 %s\n" "$(date "+%Y-%m-%d %H:%M:%S")" "$MODE" "$result" "$((SECONDS - started))" "$DEST" >> "$LOG" || true
  ' EXIT
}

if [ "$MODE" = "tar" ]; then
  start_log
  out="$DEST/dev-$(date +%Y%m%d-%H%M).tar.gz"
  echo "== tar 作成: $out =="
  # 終了コード 1 は「読み込み中にファイルが変わった」等の警告なので続行
  tar czf "$out" ${tar_path_args[@]+"${tar_path_args[@]}"} "${args[@]}" -C "$HOME" dev || {
    rc=$?
    if [ "$rc" -eq 1 ]; then
      result="警告(tar rc=$rc)"
      echo "警告: tar が一部ファイルで警告を出しました (rc=$rc)"
    else
      exit "$rc"
    fi
  }
  ls -lh "$out"

elif [ "$MODE" = "rsync" ]; then
  start_log
  target_dir="$DEST/dev"
  marker="$target_dir/.dev-backup"
  # --delete で無関係なファイルを消さないよう、このスクリプトが作ったフォルダか確認する
  if [ ! -e "$marker" ]; then
    if [ ! -d "$target_dir" ] || [ -z "$(ls -A "$target_dir")" ]; then
      mkdir -p "$target_dir"
      touch "$marker"
      echo "バックアップ先 '$target_dir' を新規に初期化しました。"
    else
      echo "エラー: '$target_dir' には既に別のファイルがあり、このスクリプトの保存先として初期化されていません。" >&2
      echo "  rsync --delete で中身が消えるため中断しました。" >&2
      echo "  このフォルダをバックアップ専用にしてよい場合のみ、次を実行してから再実行してください:" >&2
      echo "    touch '$marker'" >&2
      exit 1
    fi
  fi
  echo "== rsync: $SRC -> $target_dir =="
  # Windows ドライブ (/mnt/*) へのコピーではシンボリックリンクが作れず rc=23 になるのが普通なので、
  # 23 (一部転送失敗) と 24 (転送中にファイルが消えた) は警告扱いにして続行
  # --exclude=/.dev-backup は、目印ファイルを --delete で消されないようにするため
  rsync -a --delete --info=progress2 --no-perms --no-owner --no-group --modify-window=2 \
        --exclude=/.dev-backup ${rsync_path_args[@]+"${rsync_path_args[@]}"} "${args[@]}" "$SRC/" "$target_dir/" || {
    rc=$?
    case "$rc" in
      23|24) result="警告(rsync rc=$rc)"
             echo "警告: rsync が一部ファイルをスキップしました (rc=$rc、シンボリックリンク等)" ;;
      *)     exit "$rc" ;;
    esac
  }
  echo
  echo "== 結果 =="
  du -sh "$target_dir" 2>/dev/null || true

else
  echo "エラー: 不明なモード '$MODE' です。(指定可能: rsync, tar, check)" >&2
  exit 1
fi
