# カード抽選Discord通知

ポケモンカード／ONE PIECEカードの抽選情報を収集し、応募資格を判定してDiscordへ締切順に通知します。自動応募は行いません。

## 特徴

- 公式ページ、カードショップ、抽選まとめサイトを設定ファイルで追加可能
- 購入履歴、会員登録、アプリ、本人確認などを抽出
- 「応募可能／要確認／条件外／公式確認待ち」に分類
- 毎朝7:30の締切順ダイジェスト
- 抽選ごとの個別投稿と、Discordの✅リアクションによる応募済み管理
- GitHub Modelsによる抽選判定（商品説明・終了済み情報・不正確な日付を除外）
- 注文番号などの個人情報は保存しない

## セットアップ

1. このフォルダーをGitHubの非公開リポジトリへ登録します。
2. `config.example.yaml`を`config.yaml`としてコピーします。
3. `config.yaml`の`eligibility`を自分の状況に合わせます。分からない項目は`null`にします。
4. Discordで通知用チャンネルを作り、チャンネル設定の「連携サービス」からWebhookを作成します。
5. GitHubの `Settings > Secrets and variables > Actions` に、`DISCORD_WEBHOOK_URL`という名前でWebhook URLを登録します。
6. GitHubのActions画面で`Card lottery watcher`を手動実行します。

## 応募済みの管理

応募が終わったら、その抽選のDiscord投稿に✅リアクションを付けます。次回は同じ投稿を更新するため、✅が残り、スマホとPCで同じ状態を確認できます。

## 監視先の追加

`config.yaml`の`sources`へ追加します。

```yaml
- name: カードボックス○○店
  store_key: cardbox
  kind: official
  category: both
  url: https://example.com/lottery
```

`kind: discovery`は発見用サイト、`kind: official`は店舗公式ページです。まとめサイトの情報は公式確認待ちとして表示されます。

## ローカルテスト

```bash
cp config.example.yaml config.yaml
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt pytest
pytest -q
python -m src.main
```

Webhookが未設定なら収集だけ行い、Discordには送信しません。

## AI判定

GitHub Actionsの`GITHUB_TOKEN`でGitHub Modelsを呼び出します。追加のAPIキー登録は不要です。ワークフローには`models: read`権限が必要です。AIがページ本文から受付中または近日開始の抽選だけを抽出し、その後コード側でも次を検証します。

- 応募締切が本文にある
- 締切が過去ではない
- 締切が45日以内
- 応募URLが実際にページ内に存在する
- 信頼度が0.75以上

## 注意

- 各サイトの利用規約とrobots.txtに従ってください。
- HTML変更によって抽出できなくなることがあります。
- 応募条件と締切は必ず公式応募ページでも確認してください。
- Webhook URLをコードや`config.yaml`へ直接書かないでください。
