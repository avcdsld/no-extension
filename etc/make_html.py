import base64, os

# サブセット済みフォントを直接使う
font_path = "OCRB_subset.woff2"

if not os.path.exists(font_path):
    print(f"ERROR: {font_path} が見つかりません")
    exit(1)

with open(font_path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

size_kb = os.path.getsize(font_path) / 1024
print(f"フォント: {size_kb:.1f} KB")

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@font-face {{
  font-family: 'OCRB';
  src: url('data:font/woff2;base64,{b64}') format('woff2');
  font-weight: 400;
  font-style: normal;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: 100%; height: 100%; }}
body {{
  background: #080808;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
}}
.stmt {{
  font-family: 'OCRB', 'Courier New', monospace;
  font-size: clamp(18px, 4vw, 42px);
  font-weight: 400;
  color: #e8e8e8;
  text-align: center;
  line-height: 2.0;
  letter-spacing: 0.06em;
}}
blink {{ animation: b 1s step-end infinite; }}
@keyframes b {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0; }} }}
</style>
</head>
<body>
  <div class="stmt">
    This is<br>
    <blink>not</blink><br>
    a transaction.
  </div>
</body>
</html>"""

out = "output.html"
with open(out, "w") as f:
    f.write(html)

out_kb = os.path.getsize(out) / 1024
print(f"生成: {out} ({out_kb:.1f} KB)")
