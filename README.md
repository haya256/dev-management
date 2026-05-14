# dev-management

複数 PC の `~/dev/` 配下プロジェクトを Claude に把握させるためのスキャンツールです。

各プロジェクトの `README.md` とディレクトリ構成を収集し、PC をまたいだプロジェクト一覧の作成や内容への質問に答えられるようにします。

## 使い方

```bash
python3 scan.py
```

`~/dev/` 配下を走査し、`README.md` が存在するディレクトリを自動検出。結果を `data/pc-data/{ホスト名}/` に保存し、全 PC を統合した `data/index.md` を生成します。

```bash
python3 scan.py --merge-only
```

スキャンをスキップして `data/index.md`（全 PC 統合一覧）だけ再生成します。他 PC のデータを `git pull` した後に使います。

### 出力内容

```
data/
  .git/               # プライベートリポジトリ（data/ 自体が独立した git リポジトリ）
  .gitignore          # index.md を除外（push しない）
  index.md            # 全 PC 統合プロジェクト一覧（ローカル生成のみ）
  pc-data/
    {ホスト名}/
      meta.json       # スキャン日時・プロジェクト数
      entries.json    # マージ用機械可読データ
      index.md        # この PC のみのプロジェクト一覧
      projects/
        {project-key}/
          README.md   # 各プロジェクトの README のコピー
          tree.txt    # ディレクトリ構成（最大3階層）
```

プロジェクトキーはパスの `/` を `__` に置換したもの（例: `org/bar` → `org__bar`）。

`Main` 列は `pmo/` ディレクトリがあるプロジェクトに `YES` を表示します。

### スキャン対象外のディレクトリ

`node_modules` / `.git` / `__pycache__` / `venv` / `.venv` / `dist` / `build` / `target` / `.idea` / `.vscode`

## マルチPC セットアップ

### 1台目（初回）

```bash
python3 scan.py   # data/ が git init される

cd data
git add pc-data/
git commit -m "init: $(hostname) first scan"
gh repo create dev-management-data --private --source=. --remote=origin --push
cd ..
```

### 2台目以降

```bash
# dev-management をクローン後
git clone git@github.com:haya256/dev-management-data.git data

python3 scan.py   # 自分の PC のデータを追加・index.md を再生成

cd data
git pull --rebase origin main
git add pc-data/
git commit -m "scan: $(hostname) $(date +%Y-%m-%d)"
git push origin main
cd ..
```

### 日常の同期手順

```bash
python3 scan.py                         # スキャン

cd data
git pull --rebase origin main           # 他 PC の最新を取得
python3 ../scan.py --merge-only        # 取得後に index.md を再生成
git add pc-data/
git commit -m "scan: $(hostname) $(date +%Y-%m-%d)"
git push origin main
cd ..
```

## 仕様

- `~/dev/` は読み取りのみ。変更・削除は一切行いません
- 実行のたびに自分の PC の `data/pc-data/{ホスト名}/` を全更新します（他 PC のデータは触りません）
- ネストしたプロジェクト（親子両方に `README.md` がある場合）は両方を収集します

## ライセンス

MIT
