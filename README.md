# dev-management

`~/dev/` 配下のプロジェクトを Claude に把握させるためのスキャンツールです。

各プロジェクトの `README.md` とディレクトリ構成を収集し、Claude がそれらを読んでプロジェクト一覧の作成や内容への質問に答えられるようにします。

## 使い方

```bash
python3 scan.py
```

`~/dev/` 配下を走査し、`README.md` が存在するディレクトリを自動検出。結果を `data/` に保存します。

### 出力内容

```
data/
  index.md          # 全プロジェクトの一覧表（プロジェクト名・パス・一行説明）
  <project-key>/
    README.md       # 各プロジェクトの README のコピー
    tree.txt        # ディレクトリ構成（最大3階層）
```

プロジェクトキーはパスの `/` を `__` に置換したもの（例: `org/bar` → `org__bar`）。

### スキャン対象外のディレクトリ

`node_modules` / `.git` / `__pycache__` / `venv` / `.venv` / `dist` / `build` / `target` / `.idea` / `.vscode`

### Claude への活用例

```
data/index.md と各プロジェクトの README を読んで、プロジェクト一覧を教えて
```

```
data/my-project/README.md を読んで、このプロジェクトの使い方を説明して
```

## 仕様

- `~/dev/` は読み取りのみ。変更・削除は一切行いません
- 実行のたびに `data/` を全更新します
- ネストしたプロジェクト（親子両方に `README.md` がある場合）は両方を収集します

## ライセンス

MIT
