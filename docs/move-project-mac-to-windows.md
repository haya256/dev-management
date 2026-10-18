# Mac のプロジェクトを Windows 環境へ移動する手順

Mac で開発しているプロジェクトを Windows 環境（WSL）へ移動し、開発場所（Main）を Windows 環境に一本化するための手順です。

- 転送方法: プロジェクトを tar で固めて Google ドライブ経由で受け渡す
  - git 管理外のもの（`pmo/`・`data/`・`config/`・`.claude/settings.local.json` など）も含めて丸ごと運ぶため
- 移動後: Mac 側のプロジェクトは丸ごと削除する

以下では例として `example-project` を使います。別のプロジェクトでは `PROJ` の値だけ差し替えてください。

---

## 0. 準備

Mac と Windows 環境（WSL）の両方のターミナルで、最初に変数を設定します。

```bash
PROJ=example-project
```

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

## 2. Mac: tar で固めて Google ドライブへ置く

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

### （任意）Claude Code のメモリも一緒に運ぶ

Claude Code のプロジェクト別メモリは、PC ごとのパスに紐づいています。そのため移動先では自動で引き継がれません。引き継ぎたい場合は、別の tar にしておきます。

```bash
ls ~/.claude/projects/ | grep -- "-dev-$PROJ$"    # 例: -Users-<macユーザー>-dev-example-project
tar -czf ~/Desktop/$PROJ-claude-memory.tar.gz -C ~/.claude/projects/<上で見つけたディレクトリ名> memory
```

### Google ドライブへアップロード

次のどちらかの方法で、作った tar（メモリ用もあればそれも）を置きます。

- Finder で Google ドライブ（`~/Library/CloudStorage/GoogleDrive-*/マイドライブ/`）にコピーする
- ブラウザで drive.google.com にアップロードする

---

## 3. Windows 環境: 受け取りと展開

1. Windows 側で tar をダウンロードする
   - ブラウザでダウンロードした場合: `C:\Users\<Windowsユーザー>\Downloads\`
   - Google Drive for desktop を使っている場合: `G:\マイドライブ\` からダウンロードフォルダへコピーする
2. WSL に移動先が無いことを確認する

   ```bash
   ls -d ~/dev/$PROJ 2>/dev/null && echo "既に存在します。退避または削除してから続行" || echo "OK"
   ```

   - clone が既にある場合は、中に未 push の作業がないことを確認してから削除（または `mv ~/dev/$PROJ ~/dev/$PROJ.old` で退避）します
3. 展開する

   ```bash
   WIN_DL=/mnt/c/Users/<Windowsユーザー>/Downloads
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

5. （任意）Claude Code のメモリを展開する

   ```bash
   mkdir -p ~/.claude/projects/-home-$USER-dev-$PROJ
   tar -xzf $WIN_DL/$PROJ-claude-memory.tar.gz -C ~/.claude/projects/-home-$USER-dev-$PROJ
   ```

---

## 4. Windows 環境: 動作確認と調整

1. git の確認

   ```bash
   cd ~/dev/$PROJ
   git status        # clean（または Mac と同じ未コミット状態）であること
   git remote -v
   git fetch         # WSL 側の GitHub 認証で通ること
   ```

2. Mac の絶対パスが残っていないか探す

   ```bash
   grep -rn "/Users/" .claude config 2>/dev/null
   ```

   - ヒットした箇所は WSL のパス（`/home/<WSLユーザー>/...`）に直すか、不要なら削除します。`.claude/settings.local.json` の許可コマンドなどに残っていることがあります
3. 実行環境を作り直す（プロジェクトに応じて）

   ```bash
   python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt   # Python
   npm install                                                                         # Node.js
   ```

4. 主要なスクリプトを1つ動かして、正常に動くことを確認する
   - 例: `python3 scripts/main.py` など、普段使っているコマンド
5. `~/dev/$PROJ` で Claude Code を起動し、`pmo/README.md` を読ませて状況を把握できることを確認する

---

## 5. dev-management に反映する（Windows 環境）

```bash
cd ~/dev/dev-management
python3 scan.py
cd data
git pull --rebase origin main
cd ..
python3 scan.py --merge-only
cd data
git add pc-data/
git commit -m "scan: $(hostname) $(date +%Y-%m-%d)"
git push origin main
cd ..
grep "$PROJ" data/index.md
```

- `data/index.md` で、`$PROJ` の Windows 環境のホスト名の列が `Main` になっていることを確認します
- この時点では Mac 側にもまだ残っているので、Mac のホスト名の列にも `Main` が出ます。これは次の手順で解消します

---

## 6. Mac: 削除と後片付け

**Windows 環境での動作確認がすべて済んでから**行ってください。

1. プロジェクトと作業用の tar を削除する

   ```bash
   rm -rf ~/dev/$PROJ
   rm -f ~/Desktop/$PROJ.tar.gz ~/Desktop/$PROJ-claude-memory.tar.gz
   ```

2. （任意）Claude Code のメモリも削除する: `~/.claude/projects/-Users-<macユーザー>-dev-$PROJ/`
3. Mac でスキャンして push する

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
4. Windows 環境で `data/` を pull し、`python3 scan.py --merge-only` を実行する。`$PROJ` が Windows 環境だけに出ることを確認します
5. Google ドライブ上の tar は、しばらくバックアップとして残します。問題がなければ削除してください

---

## 7. チェックリスト

- [ ] Windows 環境の `~/dev/$PROJ/pmo/` がある
- [ ] Windows 環境で `git status` が想定どおり（日本語ファイル名の崩れがない）
- [ ] `.claude/`・`config/` に Mac のパス（`/Users/...`）が残っていない
- [ ] 主要スクリプトが Windows 環境で動く
- [ ] `data/index.md` で `$PROJ` が Windows 環境の `Main` だけになっている
- [ ] Mac の `~/dev/$PROJ` を削除した
- [ ] Google ドライブの tar を（しばらくしてから）削除した
