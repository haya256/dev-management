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

### PC環境の点検

`scan.py` はプロジェクトのスキャンと一緒に、その PC の OS の更新状況を点検して記録します。

| 環境 | 記録する内容 |
|------|------|
| Linux（Ubuntu など） | OS・カーネル、最後に apt で更新した日時、最後に `apt update` した日時、更新待ちの件数（うちセキュリティ更新） |
| WSL の場合の Windows 側 | Windows のビルド番号、最後に入った更新プログラム、未適用の Windows Update（ドライバーとオプションの更新プログラムは除く）、WSL のバージョン |
| macOS | OS のバージョン、最後に入ったソフトウェアアップデート、未適用のアップデート |

あわせて、入っているパッケージの一覧（`dpkg-query` / `brew list --versions`）を保存します。脆弱性が出たときに、別の PC からでも照合できるようにするためです。

点検は読み取り専用のコマンドだけで行い、更新のダウンロードやインストールはしません。Windows Update の確認には数十秒かかることがあります。

```bash
python3 scan.py --skip-env
```

環境点検をスキップします（前回の点検結果は残します）。

### 出力内容

```
data/
  .git/               # プライベートリポジトリ（data/ 自体が独立した git リポジトリ）
  .gitignore          # index.md を除外（push しない）
  index.md            # 全 PC 統合プロジェクト一覧・PC環境の一覧（ローカル生成のみ）
  pc-data/
    {ホスト名}/
      meta.json       # スキャン日時・プロジェクト数
      entries.json    # マージ用機械可読データ
      index.md        # この PC のみのプロジェクト一覧
      env.json        # OS の更新状況（機械可読）
      env.md          # OS の更新状況（人が読む用）
      packages.txt    # 入っているパッケージの一覧
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
git clone git@github.com:{your-username}/dev-management-data.git data

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

### プロジェクトを別 PC へ移動する

[docs/move-project-mac-to-windows.md](docs/move-project-mac-to-windows.md) — Mac のプロジェクトを Windows 環境（WSL）へ移す手順

## 仕様

- `~/dev/` は読み取りのみ。変更・削除は一切行いません
- PC環境の点検も読み取りのみ。パッケージの更新や設定変更は行いません
- 実行のたびに自分の PC の `data/pc-data/{ホスト名}/` を全更新します（他 PC のデータは触りません）
- ネストしたプロジェクト（親子両方に `README.md` がある場合）は両方を収集します

## ライセンス

MIT
