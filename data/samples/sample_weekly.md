## 📊 週次データ
- **主要な取り組み**: Antigravity プロジェクトの Docker ネットワーク修正、AtCoder ABC440 への参加 (A, B完)、TFT Set 16 のメタ研究
- **完了タスク**: 
  - `docker-compose.yml` のポート設定修正
  - `cognizer.py` のリファクタリング (動的サンプル読み込み)
  - 競技プログラミング 3問 AC (AtCoder Begginer Contest)

## 🛠 プロジェクト別進捗
### MyLocalLLM Daily Log (Local LLM)
- **進捗**: コンテナ間通信の接続拒否エラーを解決し、RAG 用の ChromaDB が正常に動作するようになった。
- **課題**: `sensor.py` のメモリリークが未解決。長時間稼働でメモリ使用量が増加する傾向がある。

### University/Assignments
- **進捗**: 今週は特筆すべき課題活動なし。

### Competitive Programming
- **進捗**: ABC440 に参加。A問題とB問題はスムーズに解けたが、C問題で TLE (Time Limit Exceeded) に苦戦した。
- **課題**: C++ の `std::vector` と `std::set` の使い分けによるパフォーマンス差の理解不足。

## 💡 今週の学び (Learnings)
- **Docker Networking**: `localhost` はコンテナ内でループバックを指すため、他コンテナへの通信にはサービス名を使用する必要がある。
- **C++ STL**: `std::vector` の範囲外アクセスは未定義動作ではなく、デバッグモードでは明確な Assertion Error として検出できる。

## 📝 来週のアクション
- `sensor.py` のメモリプロファイリングを実施し、リーク箇所を特定する。
- 競技プログラミングの典型アルゴリズム (特に計算量見積もり) を復習する。
