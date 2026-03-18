# Polyglot Transaction 解説

Bitcoin トランザクションの生バイナリが、同時に別のファイル形式としても有効な
「Polyglot (多言語)」ファイルを構築する技法の解説。

---

## 概要

Bitcoin のトランザクションはバイナリ形式で保存される。
このバイナリを `.tiff` / `.html` / `.pdf` / `.zip` などの拡張子で保存すると、
対応するアプリケーションで開ける — これが Polyglot Transaction である。

鍵となるのは、各ファイル形式のパーサーが「ファイルの先頭バイトをどう解釈するか」の違いを利用すること。

---

## TIFF Polyglot の仕組み

### TIFF ファイルフォーマット

TIFF ファイルの先頭 8 バイト:

```
offset 0-1: バイトオーダー (0x4D4D = big-endian "MM", または 0x4949 = little-endian "II")
offset 2-3: マジックナンバー 42 (0x002A)
offset 4-7: IFD (Image File Directory) オフセット (最初の IFD の位置)
```

### SegWit トランザクションの先頭バイト

```
offset 0-3: tx version (4 bytes, little-endian)
offset 4:   SegWit marker (0x00)
offset 5:   SegWit flag (0x01)
offset 6:   vin count (1 byte, < 253 の場合)
offset 7-:  最初の vin の txid (32 bytes, internal byte order)
```

### Polyglot の重ね合わせ

tx version を `0x4D4D002A` に設定すると、ファイルの先頭 4 バイトが TIFF マジック `MM\x00\x2A` と一致する。

```
TIFF: [MM]  [42]   [IFD offset (4 bytes)]
Bitcoin: [tx version] [00] [01] [vin_count] [txid_byte_0]
```

bytes 4-7 は TIFF では IFD オフセットとして解釈される:

```
IFD offset = 0x0001XXYY
  XX = vin count
  YY = txid の先頭バイト (internal byte order)
```

txid の先頭バイトを グラインディング (funding tx の change amount を調整) で制御し、
IFD が witness データ内の正しい位置を指すようにする。

### IFD の配置

IFD (Image File Directory) は TIFF のメタデータ構造で、画像の幅・高さ・圧縮方式・
各ストリップの位置とサイズなどを格納する。

IFD は最後の vin の witnessScript 内に埋め込まれる:

```
witnessScript:
  PUSH(pubkey) CHECKSIGVERIFY    # 署名検証
  SHA256 PUSH(hash) EQUALVERIFY  # データ検証 (各 witness item)
  ...
  PUSH(filler)                   # IFD 位置合わせ用パディング
  PUSHDATA1(ifd_bytes)           # IFD データ (174 bytes)
  OP_2DROP                       # スタッククリーンアップ
```

### 画像データの格納

画像の各行 (strip) は deflate 圧縮され、個別の witness item として格納される:

```
witness:
  item 0:  padding (xres/yres 値を含む)
  item 1:  strip 0 (deflate 圧縮された 1 行目)
  item 2:  strip 1
  ...
  item N:  strip N-1
  item N+1: signature (71 bytes)
  item N+2: witnessScript
```

各 witness item は 520 バイト以下でなければならない (BIP141)。
これにより、1 行の圧縮後サイズが 520 バイトを超える画像は使用できない。

### 複数 vin の利用

1 つの vin あたり最大 64 witness item (データ + 署名 + スクリプト) を格納できる。
画像の行数が 63 を超える場合、複数の vin に分散する:

```
vin[0]:  pad + strip 0-62  (最大 63 strips)
vin[1]:  strip 63-126      (最大 64 strips)
vin[2]:  strip 127-...
...
vin[N-1]: metadata (StripOffsets, StripByteCounts, BitsPerSample 等) + IFD
```

最後の vin にはメタデータ配列と IFD が格納される。
メタデータ配列 (StripOffsets, StripByteCounts) のサイズは `行数 × 4 バイト` なので、
最大行数は `520 / 4 = 130` に制限される。

### グラインディング

funding tx の txid の先頭バイト (internal order) が IFD オフセットの一部になるため、
目的のバイト値になるまで funding tx の change amount を微調整する。

1 バイトのグラインディングなので、平均 ~128 回の試行で一致する。

---

## HTML Polyglot の仕組み

tx version を標準の `0x02000000` (version 2) に設定。

HTML5 パーサーは非常に寛容で、ファイル先頭のバイナリゴミを無視し、
`<html>` タグを見つけた時点からレンダリングを開始する。

### チャンク間の varint 処理

witness item 間にはバイト長を示す varint が挿入される。
これが HTML コンテンツを壊さないよう、以下の対策を行う:

- **HTML タグ境界で分割**: チャンク境界を `>` の直後に置き、タグを分断しない
- **HTML コメント**: タグ境界で分割できる場合、`<!--` と `-->` で varint を囲む
- **CSS コメント**: `<style>` 内では `/*` と `*/` で varint を囲む
- **Base64 区間**: フォントデータ等の Base64 文字列内では、ブラウザの Base64 デコーダーが不正バイトを無視するためコメント不要
- **バイナリ非表示**: `body { font-size: 0 }` で tx ヘッダ/署名のバイナリゴミを非表示にし、コンテンツ要素で `font-size` を再指定

---

## PDF Polyglot の仕組み

tx version を標準の `0x02000000` (version 2) に設定。

PDF パーサーはファイル先頭 1024 バイト内で `%PDF` シグネチャを検索する。
tx ヘッダの後、witness データ内に `%PDF-1.4` ヘッダと PDF オブジェクトを配置する。

### オブジェクト境界での分割

PDF はバイト位置に厳密 (xref テーブルがオブジェクトの絶対位置を指す) なので、
witness item 間の varint がオブジェクト内部に入ると壊れる。

対策:
- **endobj 境界で分割**: 各 PDF オブジェクトが 1 つの witness item に収まるようにする (≤ 520B)
- **PDF コメント**: オブジェクト間で `\n%` と `\n` を使い、varint を PDF コメントに包む
- **xref 再計算**: varint とコメントマーカーのバイト数を含めた正確なファイル内オフセットを計算

### ストリーム分割

PDF のコンテントストリーム (描画コマンド) が 520B を超える場合、
複数の content stream オブジェクトに分割し、`/Contents [4 0 R 5 0 R]` の配列で参照する。
各 BT...ET ブロック (テキスト描画単位) は独立しているため、分割しても描画に影響しない。

---

## ZIP Polyglot の仕組み

tx version を標準の `0x02000000` (version 2) に設定。

ZIP は**末尾から解析**する。End of Central Directory (EOCD) をファイル末尾で探し、
Central Directory → Local File Header と逆方向に辿る。
ファイル先頭の tx ヘッダは ZIP パーサーに無視される。

witness データ内に以下を配置:
- Local File Header + ファイルデータ
- Central Directory
- EOCD

ZIP の各オフセット (Local File Header の位置、Central Directory の位置) は
witness 内の絶対位置を正確に計算して設定する。

---

## tx version と relay policy

| フォーマット | tx version | メインネット relay |
|---|---|---|
| TIFF | `0x2A004D4D` (非標準) | 不可 (マイナー直接送信が必要) |
| HTML | `0x00000002` (version 2) | 可能 |
| PDF | `0x00000002` (version 2) | 可能 |
| ZIP | `0x00000002` (version 2) | 可能 |

Bitcoin Core の relay policy は tx version 1 と 2 のみを標準として中継する。
TIFF は TIFF マジックを tx version に使う必要があるため非標準となる。
HTML / PDF / ZIP は先頭バイトの制約がないため version 2 を使用でき、
通常のメインネット中継が可能。

---

## BIP-110 との関係

BIP-110 は witness item のサイズ上限を 520B から 80B に縮小する提案。
導入されると:

- 520B のチャンクが使えなくなり、Polyglot Transaction の構築が**不可能**になる
- 既にブロックに入った tx は影響を受けない (ソフトフォークは過去のブロックを無効にしない)
- データを複数 tx に分散すれば保存は可能だが、「1 tx = 1 ファイル」の等式が成立しなくなる

Polyglot Transaction は「トランザクションそのものがファイルである」ことに意味がある。
BIP-110 が禁じるのはデータの保存ではなく、この**等式**である。

---

## 参考

- [knotslies.com](https://knotslies.com/) — 最初の Polyglot Transaction (TIFF) の実証
- BIP-141: Segregated Witness
- BIP-110: Restrict transaction witness sizes (提案中)
