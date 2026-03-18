import base64, os

# サブセット済みフォントを直接使う
font_path = "OCRB_subset.woff2"

if not os.path.exists(font_path):
    print(f"ERROR: {font_path} が見つかりません")
    exit(1)

with open(font_path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

CHUNK = 400
chunks = [b64[i:i+CHUNK] for i in range(0, len(b64), CHUNK)]
font_tags = "\n".join(f"<i id=f{i}>{c}</i>" for i, c in enumerate(chunks))

html = f"""<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: 100%; height: 100%; }}
body {{
  background: #080808;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  font-size: 0;
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
{font_tags}
<div class="stmt">
  This is<br>
  <blink>not</blink><br>
  a transaction.
</div>
<script>var b='';for(var i=0;document.getElementById('f'+i);i++)b+=document.getElementById('f'+i).textContent.replace(/[^A-Za-z0-9+/=]/g,'');var f=new FontFace('OCRB','url(data:font/woff2;base64,'+b+')');document.fonts.add(f);f.load().then(function(){{document.querySelector('.stmt').style.fontFamily="'OCRB',monospace"}})</script>
</body>
</html>"""

out = "output.html"
with open(out, "w") as f:
    f.write(html)

size_kb = os.path.getsize(font_path) / 1024
print(f"font: {size_kb:.1f} KB ({len(chunks)} chunks)")
print(f"output: {out} ({os.path.getsize(out)} bytes)")
