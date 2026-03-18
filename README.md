# no extension

A Bitcoin transaction that is also a file.

## How it works

The file data lives in the witness. Standard version 2, relayable on mainnet.

| Format | Technique |
|--------|-----------|
| HTML | Parsers ignore leading binary, start at `<html>` |
| PDF | Parsers scan for `%PDF` within the first 1024 bytes |
| ZIP | Parsers read from the end (EOCD), ignoring the beginning |

[BIP-110](https://github.com/bitcoin/bips/blob/master/bip-0110.mediawiki) proposes reducing the witness item size limit from 520 to 80 bytes. If adopted, polyglot transactions become impossible to construct. Data can still be spread across multiple transactions, but the equation — one transaction equals one file — breaks. What BIP-110 prohibits is not data storage on the blockchain. It is this equation.

## Usage

```
python3 inscribe.py prepare <format> <input> [--network NET] [--wallet NAME]
python3 inscribe.py fund <state.json>
python3 inscribe.py build <state.json> [-o output]
python3 inscribe.py broadcast <state.json>
```

### Example

```bash
python3 inscribe.py prepare html data/input.html --wallet polyglot_wallet
python3 inscribe.py fund state_html.json
python3 inscribe.py build state_html.json -o tmp/output.html
python3 inscribe.py broadcast state_html.json
bitcoin-cli getrawtransaction <txid> | xxd -r -p > tmp/from_chain.html
```

---

## Setup

Requires Python 3 with `Pillow` and `ecdsa`:

```bash
pip install Pillow ecdsa
```

Requires Bitcoin Core with a funded wallet. For local testing:

```bash
mkdir -p ~/Library/Application\ Support/Bitcoin
cat > ~/Library/Application\ Support/Bitcoin/bitcoin.conf << 'EOF'
regtest=1
server=1
txindex=1
[regtest]
rpcuser=test
rpcpassword=test
acceptnonstdtxn=1
EOF

bitcoind -regtest -daemon

bitcoin-cli -regtest createwallet "polyglot_wallet"
bitcoin-cli -regtest generatetoaddress 101 $(bitcoin-cli -regtest -rpcwallet=polyglot_wallet getnewaddress)
```

---

This work builds on ideas from [knotslies.com](https://knotslies.com/).
