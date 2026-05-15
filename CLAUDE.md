# dev-management — Claude 向けガイド

## このプロジェクトの目的

`~/dev/` 配下の全プロジェクトをスキャンし、複数 PC にまたがる開発状況を一元管理するツール。
`scan.py` を実行すると `data/` にプロジェクト情報が集約され、Claude がそれを読んで質問に答えられる。

## セットアップ状況の確認

まず `data/` ディレクトリの状態を確認すること。

```bash
ls data/
```

### パターン A: `data/` が存在しない（このPCでの初回セットアップ）

プライベートリポジトリを `data/` としてクローンする:

```bash
git clone https://github.com/{your-username}/dev-management-data.git data
```

クローン後、スキャンを実行:

```bash
python3 scan.py
```

このPCのデータを push:

```bash
cd data
git add pc-data/
git commit -m "scan: $(hostname) $(date +%Y-%m-%d)"
git push origin main
cd ..
```

### パターン B: `data/` は存在するがスキャンが古い

最新データに更新してからスキャン:

```bash
cd data && git pull --rebase origin main && cd ..
python3 scan.py
cd data
git add pc-data/
git commit -m "scan: $(hostname) $(date +%Y-%m-%d)"
git push origin main
cd ..
```

### パターン C: スキャン済みで最新の状態

そのまま質問に答えられる状態。必要に応じて再スキャンを促す。

---

## プロジェクト情報の読み方

セットアップ完了後、ユーザーから質問があった場合は以下を読む:

1. `data/index.md` — 全 PC 統合のプロジェクト一覧（PC 名・Main 判定・説明）
2. `data/pc-data/{hostname}/index.md` — 特定 PC のみの一覧
3. `data/pc-data/{hostname}/projects/{key}/README.md` — 個別プロジェクトの詳細
4. `data/pc-data/{hostname}/projects/{key}/tree.txt` — ディレクトリ構成

`Main` 列が `YES` のプロジェクトは、そのPCに `pmo/` ディレクトリがある（＝メインの開発場所）。

---

## scan.py コマンドリファレンス

```bash
python3 scan.py               # ~/dev/ をスキャン → data/ を更新
python3 scan.py --merge-only  # スキャンなし、index.md だけ再生成（git pull 後に使う）
```

---

## data/ リポジトリの同期手順（日常運用）

```bash
# 1. スキャン
python3 scan.py

# 2. 他PCの最新を取得 → index.md 再生成
cd data
git pull --rebase origin main
cd ..
python3 scan.py --merge-only

# 3. push
cd data
git add pc-data/
git commit -m "scan: $(hostname) $(date +%Y-%m-%d)"
git push origin main
cd ..
```

---

## 重要な制約

- `~/dev/` を Claude が直接参照することは禁止。`scan.py` 経由でのみアクセスする
- `data/index.md` は push しない（`.gitignore` で除外済み）。各PCでローカル再生成する
- `data/pc-data/{自分のホスト名}/` 以外は削除・変更しない
