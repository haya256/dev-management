# Mac のプロジェクトを Windows 環境へ移動する手順

Mac で開発しているプロジェクトを Windows 環境（WSL）へ移動し、開発場所（Main）を Windows 環境に一本化するための手順です。

- 転送方法: プロジェクトを tar で固めて Taildrop（Tailscale）で受け渡す
  - git 管理外のもの（`pmo/`・`data/`・`config/`・`.claude/settings.local.json` など）も含めて丸ごと運ぶため
  - Taildrop が使えない場合は Google ドライブ経由でも可
- Claude Code のセッション履歴・メモリも一緒に運ぶ（`claude --resume` で Mac 時代の会話を再開できる）
- 移動後: Mac 側のプロジェクトは丸ごと削除する

以下では例として `example-project` を使います。別のプロジェクトでは `PROJ` の値だけ差し替えてください。

---

## 0. 準備

Mac と Windows 環境（WSL）の両方のターミナルで、最初に変数を設定します。

```bash
PROJ=example-project
```

- 新しいターミナルを開いたら、その都度設定し直すこと（未設定のまま `rm -rf ~/dev/$PROJ` を実行すると `~/dev/` 全体が消えます）
- Mac 側の場所: `~/dev/$PROJ`
- Windows 環境側の場所: WSL の `~/dev/$PROJ`
  - `/mnt/c/...`（Windows 側）には置かないこと。パーミッションが崩れ、動作も遅くなります

---

## 1. Mac: 移動前の確認

1. このプロジェクトで開いている Claude Code やエディタを閉じる
2. git 管理されている場合は、状態を確認する

   ```bash
   cd ~/dev/$PROJ
   git status                 # 未コミットの変更
   git stash list             # stash の有無
   git log --oneline @{u}..   # 未 push のコミット（リモートがある場合）
   ```

   - tar で丸ごと運ぶので、push は必須ではありません。ただし GitHub を最新にしておくと、万一のときに安全です
3. サイズを確認する

   ```bash
   du -sh ~/dev/$PROJ
   ```

   - `node_modules/` や `.venv/` など、移動先で作り直せるものは次の手順で除外します

---

## 2. Mac: tar で固めて送る

### プロジェクト本体

```bash
COPYFILE_DISABLE=1 tar --no-xattrs \
  --exclude='.DS_Store' --exclude='node_modules' --exclude='.venv' --exclude='__pycache__' \
  -czf ~/Desktop/$PROJ.tar.gz -C ~/dev $PROJ
```

- `COPYFILE_DISABLE=1` と `--no-xattrs` は、macOS 特有の `._*` ファイルや拡張属性が混ざるのを防ぐための指定です

中身を確認します。`pmo/`・`.git/`・`.claude/` が入っていれば OK です。

```bash
tar -tzf ~/Desktop/$PROJ.tar.gz | grep -E "^$PROJ/(pmo|\.git|\.claude)/$"
```

### Claude Code のセッション履歴とメモリ

Claude Code は、プロジェクトごとのデータを `~/.claude/projects/<フォルダ>/` に保存しています。フォルダ名はプロジェクトの絶対パスの `/` を `-` に置き換えたものです。

- Mac: `/Users/<macユーザー>/dev/example-project` → `-Users-<macユーザー>-dev-example-project`
- WSL: `/home/<WSLユーザー>/dev/example-project` → `-home-<WSLユーザー>-dev-example-project`

パスが変わるとフォルダ名も変わるので、自動では引き継がれません。フォルダを丸ごと固めて運びます。中身は次のとおりです。

- `<セッションID>.jsonl`: 会話履歴（`claude --resume` の一覧に出るもの）
- `<セッションID>/`: サブエージェントの記録など
- `memory/`: プロジェクトのメモリ
- `sessions-index.json`

```bash
SRC=$(ls ~/.claude/projects/ | grep -- "-dev-$PROJ$")
echo $SRC                           # 例: -Users-xxx-dev-example-project
ls ~/.claude/projects/$SRC          # *.jsonl と memory/ があるはず

COPYFILE_DISABLE=1 tar --no-xattrs -czf ~/Desktop/$PROJ-claude.tar.gz -C ~/.claude/projects/$SRC .
```

- `memory/MEMORY.md` が空でも異常とは限りません。メモリの内容をプロジェクトのスキル（`.claude/skills/`）や `CLAUDE.md` に移していることがあり、その場合はプロジェクト本体の tar で運べています

### Taildrop で送る

1. Finder でデスクトップの `$PROJ.tar.gz` と `$PROJ-claude.tar.gz` を選ぶ
2. 右クリック →「共有」→「Tailscale」→ 送り先（Windows 環境の PC）を選ぶ
   - 「共有」に Tailscale が無いときは、「共有」→「編集…」（または システム設定 → 機能拡張 → 共有）で Tailscale を有効にする

ターミナルから送ることもできます。

```bash
alias tailscale=/Applications/Tailscale.app/Contents/MacOS/Tailscale   # tailscale コマンドが無い場合
tailscale status                                                       # 送り先の名前を確認
tailscale file cp ~/Desktop/$PROJ.tar.gz ~/Desktop/$PROJ-claude.tar.gz <送り先名>:
```

- 送り先の名前は Tailscale 上の名前です。WSL のホスト名とは違うことがあります
- 最後の `:` は必須です

（Taildrop が使えない場合）Google ドライブ（`~/Library/CloudStorage/GoogleDrive-*/マイドライブ/` または drive.google.com）に置き、Windows 側でダウンロードします。

---

## 3. Windows 環境: 受け取りと展開

1. 受け取りを確認する
   - Windows 側の Tailscale で受け取った場合、`C:\Users\<Windowsユーザー>\Downloads\` に自動で保存されます
   - WSL の中の Tailscale で受け取る場合は `sudo tailscale file get ~/inbox/` で取り出し、以降の `WIN_DL` を `~/inbox` に読み替えます

   ```bash
   WIN_DL=/mnt/c/Users/<Windowsユーザー>/Downloads
   ls -lh $WIN_DL/$PROJ.tar.gz $WIN_DL/$PROJ-claude.tar.gz
   ```

   - `ls $WIN_DL/` の一覧が `Input/output error` で途中までしか出ないことがあります。上のようにファイル名を直接指定すれば確認できます
2. WSL に移動先が無いことを確認する

   ```bash
   ls -d ~/dev/$PROJ 2>/dev/null && echo "既に存在します。退避または削除してから続行" || echo "OK"
   ```

   - clone が既にある場合は、中に未 push の作業がないことを確認してから削除（または `mv ~/dev/$PROJ ~/dev/$PROJ.old` で退避）します
3. 展開する

   ```bash
   tar -xzf $WIN_DL/$PROJ.tar.gz -C ~/dev
   ```

4. 日本語ファイル名をチェックする
   - Mac では、日本語ファイル名が濁点・半濁点を分けた形（NFD）で保存されていることがあります。そのまま Linux に持ってくると、git が別のファイルとして扱います
   - `git status` を実行して、身に覚えのない「削除」と「未追跡ファイル」が日本語名で大量に出たらこの問題です。その場合は次で直します

   ```bash
   cd ~/dev/$PROJ
   git status
   # 崩れていた場合のみ
   sudo apt install -y convmv
   convmv -r -f utf8 -t utf8 --nfc --notest ~/dev/$PROJ
   git status    # clean に戻ったことを確認
   ```

5. Claude Code のセッション履歴とメモリを展開し、中の Mac のパスを WSL のパスに置き換える

   ```bash
   DST=/home/$USER/.claude/projects/-home-$USER-dev-$PROJ
   mkdir -p "$DST"
   tar -xzf $WIN_DL/$PROJ-claude.tar.gz -C "$DST"

   # Mac の ._* ファイルが混ざっていたら削除
   find "$DST" -name '._*' -delete

   # バックアップを取ってから、Mac のパスを置き換える
   tar -czf ~/$PROJ-claude-before-fix.tar.gz -C "$DST" .
   MACUSER=<macユーザー>
   grep -rl "/Users/" "$DST" | xargs -r sed -i \
     -e "s#/Users/$MACUSER/\.claude/projects/-Users-$MACUSER-dev-$PROJ#/home/$USER/.claude/projects/-home-$USER-dev-$PROJ#g" \
     -e "s#/Users/$MACUSER/#/home/$USER/#g"

   # 残りを確認（会話の文章に出てくる "/Users/..." などは残っていても問題なし）
   grep -roh '.\{20\}/Users/.\{20\}' "$DST"
   ```

   - フォルダ名が `-` で始まるので、相対パスでコマンドに渡すとオプションと解釈されて失敗します（`sed: invalid option -- 'h'` など）。上のように絶対パスを使います
   - `tar: Ignoring unknown extended header keyword 'LIBARCHIVE.xattr...'` という警告は、Mac の拡張属性を読み飛ばしただけなので無視して OK です
   - `sessions-index.json` の `originalPath` に古い場所（`~/github/...` など）が残っていたら、`/home/<WSLユーザー>/dev/$PROJ` に直します

---

## 4. Windows 環境: 動作確認と調整

1. git の確認

   ```bash
   cd ~/dev/$PROJ
   git status        # clean（または Mac と同じ未コミット状態）であること
   git remote -v
   git fetch         # WSL 側の GitHub 認証で通ること（リモートが無ければ不要）
   ```

2. Mac のファイルやパスが残っていないか探す

   ```bash
   find . -name '._*' | head                     # 出たら find . -name '._*' -delete
   grep -rn "/Users/" .claude config deploy 2>/dev/null
   ```

   - ヒットした箇所は WSL のパス（`/home/<WSLユーザー>/...`）に直すか、不要なら削除します。`.claude/settings.local.json` の許可コマンドなどに残っていることがあります
3. 実行環境を作り直す（プロジェクトに応じて）

   ```bash
   python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt   # Python
   npm install                                                                         # Node.js
   ```

4. テストや主要なスクリプトを動かして、正常に動くことを確認する
   - 例: `python3 -m unittest`、`python3 scripts/main.py` など、普段使っているコマンド
   - VPS などにデプロイしているプロジェクトは、WSL から `ssh <ホスト> true` で接続できるかも確認します（SSH 鍵と `~/.ssh/config` が必要）
5. Claude Code のセッションを確認する

   ```bash
   cd ~/dev/$PROJ && claude --resume
   ```

   - Mac 時代のセッションが一覧に出れば OK です。再開したら、最初に「Mac から WSL に移った」と伝えるとスムーズです

---

## 5. dev-management に反映する（Windows 環境）

```bash
cd ~/dev/dev-management
cd data && git pull --rebase origin main && cd ..
python3 scan.py
cd data
git add pc-data/
git commit -m "scan: $(hostname) $(date +%Y-%m-%d)"
git push origin main
cd ..
grep "$PROJ" data/index.md
```

- 先に pull してからスキャンします。スキャン後に pull すると、未コミットの変更があるため `cannot pull with rebase: You have unstaged changes.` で止まります
- `data/index.md` で、`$PROJ` の Windows 環境のホスト名の列が `Main` になっていることを確認します
- この時点では Mac 側にもまだ残っているので、Mac のホスト名の列にも `Main` が出ます。これは次の手順で解消します

---

## 6. Mac: 削除と後片付け

**Windows 環境での動作確認がすべて済んでから**行ってください。

1. プロジェクトと作業用の tar を削除する（`PROJ` が設定されていることを確認してから）

   ```bash
   echo "PROJ=$PROJ"          # 空なら PROJ=... を設定し直す
   rm -rf ~/dev/$PROJ
   rm -f ~/Desktop/$PROJ.tar.gz ~/Desktop/$PROJ-claude.tar.gz
   ls -d ~/dev/$PROJ 2>/dev/null && echo "まだある" || echo "消えた"
   ```

2. （任意）Claude Code のセッション履歴とメモリも削除する: `~/.claude/projects/-Users-<macユーザー>-dev-$PROJ/`
3. Mac でスキャンして push する（**必ず手順 1 で消えたことを確認してから**）

   ```bash
   cd ~/dev/dev-management
   cd data && git pull --rebase origin main && cd ..
   python3 scan.py
   cd data
   git add pc-data/
   git commit -m "scan: $(hostname) $(date +%Y-%m-%d)"
   git push origin main
   cd ..
   ```

   - `scan.py` は `pc-data/{ホスト名}/` を毎回作り直すので、Mac のデータから `$PROJ` が消えます
   - 消す前にスキャンすると、Mac の `Main` が残ったままになります。その場合は削除してからスキャンし直します
4. Windows 環境で `data/` を pull し、`python3 scan.py --merge-only` を実行する。`$PROJ` が Windows 環境だけに出る（Mac の列が `-`）ことを確認します
5. Windows の `Downloads` にある tar は、しばらくバックアップとして残します。問題がなければ削除してください

---

## 7. チェックリスト

- [ ] Windows 環境の `~/dev/$PROJ/pmo/` がある
- [ ] Windows 環境で `git status` が想定どおり（日本語ファイル名の崩れがない）
- [ ] `._*` ファイルが無く、`.claude/`・`config/` に Mac のパス（`/Users/...`）が残っていない
- [ ] テスト・主要スクリプトが Windows 環境で動く
- [ ] `claude --resume` で Mac 時代のセッションが出る
- [ ] `data/index.md` で `$PROJ` が Windows 環境の `Main` だけになっている
- [ ] Mac の `~/dev/$PROJ` を削除した
- [ ] `Downloads` の tar を（しばらくしてから）削除した
