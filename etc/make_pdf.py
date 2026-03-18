"""Generate input.pdf as raw PDF bytes. No external PDF library needed."""
from pathlib import Path

OUTPUT = Path("output.pdf")

PAGE_W, PAGE_H = 595, 842  # A4 approx
FONT_SIZE = 24

# Times-Roman glyph widths at 1000 units per em (standard 14 font metrics)
_TR = {
    ' ':250,'!':333,'"':408,'#':500,'$':500,'%':833,'&':778,'\'':333,
    '(':333,')':333,'*':500,'+':564,',':250,'-':333,'.':250,'/':278,
    '0':500,'1':500,'2':500,'3':500,'4':500,'5':500,'6':500,'7':500,
    '8':500,'9':500,':':278,';':278,'<':564,'=':564,'>':564,'?':444,
    'A':722,'B':667,'C':667,'D':722,'E':611,'F':556,'G':722,'H':722,
    'I':333,'J':389,'K':722,'L':611,'M':889,'N':722,'O':722,'P':556,
    'Q':722,'R':667,'S':556,'T':611,'U':722,'V':722,'W':944,'X':722,
    'Y':722,'Z':611,'a':444,'b':500,'c':444,'d':500,'e':444,'f':333,
    'g':500,'h':500,'i':278,'j':278,'k':500,'l':278,'m':778,'n':500,
    'o':500,'p':500,'q':500,'r':333,'s':389,'t':278,'u':500,'v':500,
    'w':722,'x':500,'y':500,'z':444,
}

def str_width(s, size):
    return sum(_TR.get(c, 500) for c in s) * size / 1000

def main():
    text = "This is not a transaction."
    text_w = str_width(text, FONT_SIZE)
    x = (PAGE_W - text_w) / 2
    y = PAGE_H / 2

    # strikethrough position for "not"
    prefix_w = str_width("This is ", FONT_SIZE)
    not_w = str_width("not", FONT_SIZE)
    strike_x1 = x + prefix_w
    strike_x2 = strike_x1 + not_w
    strike_y = y + FONT_SIZE * 0.22

    stream = (
        f'0 0 0 rg 0 0 {PAGE_W} {PAGE_H} re f '
        f'1 1 1 rg BT /F1 {FONT_SIZE} Tf {x:.2f} {y:.2f} Td ({text}) Tj ET '
        f'1 1 1 RG 1 w {strike_x1:.2f} {strike_y:.2f} m {strike_x2:.2f} {strike_y:.2f} l S'
    ).encode()

    parts = []
    offs = {}

    def add(key, data):
        offs[key] = sum(len(p) for p in parts)
        parts.append(data if isinstance(data, bytes) else data.encode())

    add('header', b'%PDF-1.4\n')
    add('cat',   b'1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n')
    add('pages', b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n')
    add('page',  f'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 {PAGE_W} {PAGE_H}]'
                 f'/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n'.encode())
    add('content', f'4 0 obj<</Length {len(stream)}>>stream\n'.encode()
                   + stream + b'\nendstream endobj\n')
    add('font',  b'5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Times-Roman>>endobj\n')

    n_objs = 6
    xref_off = sum(len(p) for p in parts)
    xref = f'xref\n0 {n_objs}\n0000000000 65535 f \n'.encode()
    obj_offs = {1: offs['cat'], 2: offs['pages'], 3: offs['page'],
                4: offs['content'], 5: offs['font']}
    for i in range(1, n_objs):
        xref += f'{obj_offs[i]:010d} 00000 n \n'.encode()
    xref += f'trailer<</Size {n_objs}/Root 1 0 R>>\nstartxref\n{xref_off}\n%%EOF\n'.encode()
    parts.append(xref)

    pdf = b''.join(parts)
    OUTPUT.write_bytes(pdf)
    print(f"output: {OUTPUT} ({len(pdf)} bytes)")

if __name__ == "__main__":
    main()
