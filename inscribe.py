#!/usr/bin/env python3

import sys, struct, zlib, hashlib, json, os, subprocess, argparse, time

try:
    from PIL import Image
except ImportError:
    sys.exit("pip install Pillow")
try:
    import ecdsa
except ImportError:
    sys.exit("pip install ecdsa")

def sha256(d): return hashlib.sha256(d).digest()
def hash256(d): return sha256(sha256(d))

def varint(n):
    if n < 0xfd: return bytes([n])
    if n <= 0xffff: return b'\xfd' + struct.pack('<H', n)
    return b'\xfe' + struct.pack('<I', n)

def push_data(d):
    n = len(d)
    if n <= 0x4b: return bytes([n]) + d
    if n <= 0xff: return b'\x4c' + bytes([n]) + d
    return b'\x4d' + struct.pack('<H', n) + d

SEQUENCE = 0xFFFFFFFF
LOCKTIME = 0
SIGHASH_ALL = 1
MAX_ITEM = 520
MAX_ITEMS_PER_VIN = 64
TIFF_VERSION = b'\x4d\x4d\x00\x2a'
STD_VERSION = b'\x02\x00\x00\x00'
OP_RETURN_SPK = b'\x6a\x0c' + b'no extension'

BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
def _bpoly(v):
    G=[0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3]; c=1
    for x in v:
        b=c>>25; c=((c&0x1ffffff)<<5)^x
        for i in range(5): c^=G[i] if((b>>i)&1) else 0
    return c
def _bhrp(h): return [ord(x)>>5 for x in h]+[0]+[ord(x)&31 for x in h]
def _conv(data,fb,tb):
    a,b,r,m=0,0,[],((1<<tb)-1)
    for v in data: a=(a<<fb)|v; b+=fb;
    while b>=tb: b-=tb; r.append((a>>b)&m)
    if b: r.append((a<<(tb-b))&m)
    return r
def segwit_addr(hrp,ver,prog):
    d=[ver]+_conv(prog,8,5)
    ck=[(_bpoly(_bhrp(hrp)+d+[0]*6)^1)>>5*(5-i)&31 for i in range(6)]
    return hrp+"1"+"".join(BECH32[x] for x in d+ck)
def p2wsh_addr(ws,net="regtest"):
    h={"regtest":"bcrt","testnet":"tb","signet":"tb","mainnet":"bc"}[net]
    return segwit_addr(h,0,list(sha256(ws)))

def keygen():
    sk=ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1); vk=sk.get_verifying_key()
    x,y=vk.pubkey.point.x(),vk.pubkey.point.y()
    return sk.to_string(),(b'\x02' if y%2==0 else b'\x03')+x.to_bytes(32,'big')

def sign71(privkey, sighash):
    sk=ecdsa.SigningKey.from_string(privkey,curve=ecdsa.SECP256k1)
    order=ecdsa.SECP256k1.order
    for i in range(1000):
        k=int.from_bytes(sha256(privkey+sighash+i.to_bytes(4,'big')),'big')%(order-1)+1
        sig=sk.sign_digest(sighash,sigencode=ecdsa.util.sigencode_der_canonize,k=k)
        if len(sig)==70: return sig+bytes([SIGHASH_ALL])
    raise RuntimeError("sig grinding failed")

def bip143(ver,prevouts,seqs,outpoint,scode,val,seq,outs,lt):
    p=ver+hash256(prevouts)+hash256(seqs)+outpoint+scode
    p+=struct.pack('<Q',val)+struct.pack('<I',seq)
    p+=hash256(outs)+struct.pack('<I',lt)+struct.pack('<I',SIGHASH_ALL)
    return hash256(p)

def witness_script(pubkey, items):
    if items:
        ws=push_data(pubkey)+b'\xad'
        for i,h in enumerate(sha256(d) for d in reversed(items)):
            ws+=b'\xa8'+push_data(h)+(b'\x87' if i==len(items)-1 else b'\x88')
    else:
        ws=push_data(pubkey)+b'\xac'
    return ws

def cli(args, net="regtest", wallet=None):
    cmd=["bitcoin-cli"]+([] if net=="mainnet" else [f"-{net}"])
    if wallet: cmd+=[f"-rpcwallet={wallet}"]
    cmd+=args
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode!=0: raise RuntimeError(f"bitcoin-cli: {r.stderr.strip()}")
    return r.stdout.strip()

def chunk_data(data, chunk_size=500):
    chunks = [data[i:i+chunk_size] for i in range(0, len(data), chunk_size)]
    vins = []
    for i in range(0, len(chunks), MAX_ITEMS_PER_VIN):
        vins.append(chunks[i:i+MAX_ITEMS_PER_VIN])
    return vins

def chunk_html(data, chunk_size=493):
    style_start = data.find(b'<style>')
    style_end = data.find(b'</style>')

    chunks = []
    pos = 0
    comment_type = None
    while pos < len(data):
        end = min(pos + chunk_size, len(data))
        in_style = style_start >= 0 and pos >= style_start and pos < style_end

        if end < len(data):
            best = -1
            for sep in [b'>', b'}\n', b';\n']:
                p = data.rfind(sep, pos, end)
                if p > pos and p + len(sep) > best:
                    best = p + len(sep)
            if best > pos:
                end = best
                use_comment = True
            else:
                use_comment = False
        else:
            use_comment = False

        chunk = data[pos:end]

        if comment_type == 'css':
            chunk = b'*/' + chunk
        elif comment_type == 'html':
            chunk = b'-->' + chunk

        if end < len(data) and use_comment:
            in_style_at_end = style_start >= 0 and end > style_start and end <= style_end
            if in_style_at_end:
                chunk += b'/*'
                comment_type = 'css'
            else:
                chunk += b'<!--'
                comment_type = 'html'
        else:
            comment_type = None

        chunks.append(chunk)
        pos = end
    vins = []
    for i in range(0, len(chunks), MAX_ITEMS_PER_VIN):
        vins.append(chunks[i:i+MAX_ITEMS_PER_VIN])
    return vins

def build_tx(version, data_per_vin, pubkey, privkey, txid_hex, values):
    vc=len(data_per_vin); ti=bytes.fromhex(txid_hex)[::-1]
    prevs=b''.join(ti+struct.pack('<I',i) for i in range(vc))
    seqs=struct.pack('<I',SEQUENCE)*vc
    oser=struct.pack('<Q',0)+bytes([len(OP_RETURN_SPK)])+OP_RETURN_SPK
    vle=struct.pack('<I',int.from_bytes(version,'little'))
    sigs=[]; wss=[]
    for vi in range(vc):
        ws=witness_script(pubkey,data_per_vin[vi]); wss.append(ws)
        sc=varint(len(ws))+ws
        sh=bip143(vle,prevs,seqs,ti+struct.pack('<I',vi),sc,values[vi],SEQUENCE,oser,LOCKTIME)
        sigs.append(sign71(privkey,sh))
    tx=bytearray(version)+b'\x00\x01'+bytes([vc])
    for i in range(vc): tx+=ti+struct.pack('<I',i)+b'\x00'+struct.pack('<I',SEQUENCE)
    tx+=b'\x01'+struct.pack('<Q',0)+bytes([len(OP_RETURN_SPK)])+OP_RETURN_SPK
    for vi in range(vc):
        items=data_per_vin[vi]; tx+=varint(len(items)+2)
        for d in items: tx+=varint(len(d))+d
        tx+=varint(len(sigs[vi]))+sigs[vi]
        tx+=varint(len(wss[vi]))+wss[vi]
    tx+=struct.pack('<I',LOCKTIME)
    return bytes(tx)

def build_ifd(w, h, n_strips, off_stripoff, off_stripbc, off_bps, off_sf, off_xr, off_yr):
    def entry(tag, typ, cnt, val):
        e = struct.pack('>HHI', tag, typ, cnt)
        if typ == 3 and cnt == 1:   e += struct.pack('>HH', val, 0)
        elif typ == 4 and cnt == 1: e += struct.pack('>I', val)
        else:                       e += struct.pack('>I', val)
        return e
    entries = [
        entry(0x0100, 4, 1, w), entry(0x0101, 4, 1, h),
        entry(0x0102, 3, 3, off_bps), entry(0x0103, 3, 1, 8),
        entry(0x0106, 3, 1, 2), entry(0x0111, 4, n_strips, off_stripoff),
        entry(0x0115, 3, 1, 3), entry(0x0116, 4, 1, 1),
        entry(0x0117, 4, n_strips, off_stripbc),
        entry(0x011a, 5, 1, off_xr), entry(0x011b, 5, 1, off_yr),
        entry(0x0128, 3, 1, 1), entry(0x013d, 3, 1, 1),
        entry(0x0153, 3, 3, off_sf),
    ]
    return struct.pack('>H', len(entries)) + b''.join(entries) + struct.pack('>I', 0)


class TiffLayout:
    IFD_SIZE = 2 + 14 * 12 + 4

    def __init__(self, strips, pubkey, vin_count, first_txid_byte, width, height,
                 sig_sizes=None):
        self.strips = strips
        self.pubkey = pubkey
        self.vin_count = vin_count
        self.first_txid_byte = first_txid_byte
        self.width = width
        self.height = height
        self.strip_count = len(strips)
        self.ifd_offset = 0x00010000 | (vin_count << 8) | first_txid_byte
        self.sig_sizes = sig_sizes or [71] * vin_count
        self._distribute_strips()
        self._compute_offsets()

    def _distribute_strips(self):
        sc = self.strip_count
        self.strips_per_vin = []
        remaining = sc
        self.strips_per_vin.append(min(63, remaining)); remaining -= self.strips_per_vin[0]
        for i in range(1, self.vin_count - 1):
            n = min(64, remaining); self.strips_per_vin.append(n); remaining -= n
        self.strips_per_vin.append(0)
        if remaining > 0:
            raise ValueError(f"cannot fit {sc} strips in {self.vin_count} vins")

    def _compute_offsets(self):
        pos = 7 + self.vin_count * 41
        pos += 14
        self.witness_start = pos
        self.strip_file_offsets = []
        self.vin_data_items = [[] for _ in range(self.vin_count)]
        strip_idx = 0
        self.xres_off = 0
        self.yres_off = 0

        for vi in range(self.vin_count - 1):
            is_first = (vi == 0)
            n_strips = self.strips_per_vin[vi]
            data_items = []
            if is_first:
                pad = (b'\x00\x00\x00\x00\x01\x00\x00\x00'
                       b'\x01\x00\x00\x00\x01\x00\x00\x00\x01')
                data_items.append(pad)
            for j in range(n_strips):
                data_items.append(self.strips[strip_idx])
                strip_idx += 1
            n_items = len(data_items) + 2
            pos += len(varint(n_items))
            for idx_d, d in enumerate(data_items):
                vl = varint(len(d))
                if is_first and idx_d == 0:
                    self.xres_off = pos + len(vl) + 3
                    self.yres_off = self.xres_off + 8
                if not (is_first and idx_d == 0):
                    self.strip_file_offsets.append(pos + len(vl))
                pos += len(vl) + len(d)
            self.vin_data_items[vi] = data_items
            sig_sz = self.sig_sizes[vi]
            pos += len(varint(sig_sz)) + sig_sz
            ws = self._build_script(data_items)
            vl = varint(len(ws))
            pos += len(vl) + len(ws)

        self._compute_last_vin(pos)

    def _build_script(self, data_items, ifd_bytes=None, filler_push=b''):
        hashes = [sha256(d) for d in reversed(data_items)]
        if hashes:
            ws = push_data(self.pubkey) + b'\xad'
            for i, h in enumerate(hashes):
                ws += b'\xa8' + push_data(h)
                ws += b'\x87' if i == len(hashes) - 1 else b'\x88'
        else:
            ws = push_data(self.pubkey) + b'\xac'
        if ifd_bytes is not None:
            ws += filler_push
            ws += b'\x4c' + bytes([len(ifd_bytes)]) + ifd_bytes
            ws += b'\x6d'
        return ws

    def _compute_last_vin(self, pos_start):
        self.last_vin_solved = False
        for n_pad in range(0, 300):
            pos = pos_start
            data_items = []
            pad_item = (b'troll' * 104)[:MAX_ITEM]
            for _ in range(n_pad):
                data_items.append(pad_item)
            bps = struct.pack('>HHH', 8, 8, 8)
            sf = struct.pack('>HHH', 1, 1, 1)
            so = b''.join(struct.pack('>I', o) for o in self.strip_file_offsets)
            sbc = b''.join(struct.pack('>I', len(s)) for s in self.strips)
            meta = [('bps', bps), ('sf', sf), ('so', so), ('sbc', sbc)]
            for _, m in meta:
                data_items.append(m)
            n_items = len(data_items) + 2
            pos += len(varint(n_items))
            meta_offsets = {}
            for d in data_items[:n_pad]:
                vl = varint(len(d))
                pos += len(vl) + len(d)
            for name, m in meta:
                vl = varint(len(m))
                meta_offsets[name] = pos + len(vl)
                pos += len(vl) + len(m)
            last_sig_sz = self.sig_sizes[-1]
            pos += len(varint(last_sig_sz)) + last_sig_sz
            n_data = len(data_items)
            script_overhead = 35 + n_data * 35

            for sv_est in [1, 3]:
                script_start = pos + sv_est
                space = self.ifd_offset - script_start - script_overhead - 2
                if space < 0: continue
                if space == 0:
                    filler_push = b''
                elif space <= 0x4b + 1:
                    fl = space - 1
                    if fl < 0: continue
                    filler_push = bytes([fl]) + b'\x00' * fl
                elif space <= 0xff + 2:
                    fl = space - 2
                    if fl < 0: continue
                    filler_push = b'\x4c' + bytes([fl]) + b'\x00' * fl
                else:
                    fl = space - 3
                    if fl < 0: continue
                    filler_push = b'\x4d' + struct.pack('<H', fl) + b'\x00' * fl

                actual = script_start + script_overhead + len(filler_push) + 2
                if actual != self.ifd_offset: continue

                ifd = build_ifd(self.width, self.height, self.strip_count,
                                meta_offsets['so'], meta_offsets['sbc'],
                                meta_offsets['bps'], meta_offsets['sf'],
                                self.xres_off, self.yres_off)
                script_len = script_overhead + len(filler_push) + 2 + len(ifd) + 1
                if len(varint(script_len)) != sv_est: continue
                if script_len > 10000: continue
                actual_filler_data = len(filler_push) - (1 if space <= 0x4b + 1 else 2 if space <= 0xff + 2 else 3) if space > 0 else 0
                if actual_filler_data > 520: continue

                self.last_vin_n_pad = n_pad
                self.last_vin_pad_item = pad_item
                self.last_vin_data_items = data_items
                self.last_vin_meta_offsets = meta_offsets
                self.last_vin_filler_push = filler_push
                self.last_vin_ifd = ifd
                self.vin_data_items[-1] = data_items
                self.last_vin_solved = True
                total = pos + sv_est + script_len + 4
                self.total_size = total
                return

        raise ValueError("layout failed: cannot determine padding")

    def get_witness_scripts(self):
        scripts = []
        for vi in range(self.vin_count):
            if vi < self.vin_count - 1:
                ws = self._build_script(self.vin_data_items[vi])
            else:
                ws = self._build_script(self.last_vin_data_items,
                                        ifd_bytes=self.last_vin_ifd,
                                        filler_push=self.last_vin_filler_push)
            scripts.append(ws)
        return scripts


def build_tiff_tx(strips, funding_txid_hex, funding_values, privkey, pubkey,
                  vin_count, width, height):
    txid_internal = bytes.fromhex(funding_txid_hex)[::-1]
    first_byte = txid_internal[0]
    out_value = 330
    spk = b'\x51\x02\x4e\x73'
    prevouts = b''.join(txid_internal + struct.pack('<I', i) for i in range(vin_count))
    sequences = struct.pack('<I', SEQUENCE) * vin_count
    outputs_ser = struct.pack('<Q', out_value) + bytes([len(spk)]) + spk
    tx_version_le = struct.pack('<I', 0x2A004D4D)

    def sign_layout(layout):
        wscripts = layout.get_witness_scripts()
        sigs = []
        for vi in range(vin_count):
            ws = wscripts[vi]
            outpoint = txid_internal + struct.pack('<I', vi)
            script_code = varint(len(ws)) + ws
            sh = bip143(tx_version_le, prevouts, sequences,
                        outpoint, script_code, funding_values[vi],
                        SEQUENCE, outputs_ser, LOCKTIME)
            sigs.append(sign71(privkey, sh))
        return sigs

    layout = TiffLayout(strips, pubkey, vin_count, first_byte, width, height)
    sigs = sign_layout(layout)
    actual_sizes = [len(s) for s in sigs]

    if actual_sizes != layout.sig_sizes:
        layout = TiffLayout(strips, pubkey, vin_count, first_byte, width, height,
                            sig_sizes=actual_sizes)
        sigs = sign_layout(layout)
        final_sizes = [len(s) for s in sigs]
        if final_sizes != actual_sizes:
            layout = TiffLayout(strips, pubkey, vin_count, first_byte, width, height,
                                sig_sizes=final_sizes)
            sigs = sign_layout(layout)

    tx = bytearray(TIFF_VERSION)
    tx += b'\x00\x01'
    tx += bytes([vin_count])
    for i in range(vin_count):
        tx += txid_internal + struct.pack('<I', i) + b'\x00' + struct.pack('<I', SEQUENCE)
    tx += b'\x01'
    tx += struct.pack('<Q', out_value)
    tx += bytes([len(spk)]) + spk

    wscripts = layout.get_witness_scripts()
    for vi in range(vin_count):
        is_last = (vi == vin_count - 1)
        data_items = layout.last_vin_data_items if is_last else layout.vin_data_items[vi]
        n_items = len(data_items) + 2
        tx += varint(n_items)
        for d in data_items:
            tx += varint(len(d)) + d
        tx += varint(len(sigs[vi])) + sigs[vi]
        tx += varint(len(wscripts[vi])) + wscripts[vi]

    tx += struct.pack('<I', LOCKTIME)
    return bytes(tx), layout

def prepare_strips(image_path, width, height):
    img = Image.open(image_path).convert('RGB')
    w, h = img.size
    if width and height:
        img = img.resize((width, height), Image.LANCZOS)
    elif w > 200 or h > 200:
        ratio = min(200/w, 200/h)
        width, height = int(w*ratio), int(h*ratio)
        img = img.resize((width, height), Image.LANCZOS)
    else:
        width, height = w, h
    strips = []
    for y in range(height):
        row = b''.join(bytes(img.getpixel((x, y))) for x in range(width))
        c = zlib.compress(row)
        if len(c) > MAX_ITEM:
            raise ValueError(f"row {y}: {len(c)}B > {MAX_ITEM}. reduce image size")
        strips.append(c)
    return strips, width, height

def tiff_vin_count(n_strips):
    if n_strips <= 63: return 2
    elif n_strips <= 127: return 3
    elif n_strips <= 191: return 4
    elif n_strips <= 255: return 5
    else: return 2 + (n_strips - 63 + 63) // 64

def make_pdf(lines, base_offset, max_stream=470):
    title = lines[0] if lines else "Document"
    body_lines = lines[1:] if len(lines) > 1 else []
    page_h=800; margin=50; line_h=14; font_sz=10; title_sz=16
    max_lines_per_page = (page_h - 2*margin) // line_h
    pages_text = [body_lines[i:i+max_lines_per_page]
                  for i in range(0, max(1,len(body_lines)), max_lines_per_page)]
    n_pages = len(pages_text)

    parts=[]; offs={}
    def add(k,t):
        offs[k]=base_offset+sum(len(p) for p in parts)
        parts.append(t if isinstance(t,bytes) else t.encode())

    all_cmds = []
    y = page_h - margin
    indent = margin + 14
    is_hex = lambda s: len(s) > 20 and all(c in '0123456789abcdef' for c in s)
    for pi in range(n_pages):
        if pi == 0:
            safe_title = title.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            all_cmds.append(f'BT /F2 {title_sz} Tf {margin} {y} Td ({safe_title}) Tj ET')
            y -= line_h * 2
        for line in pages_text[pi]:
            raw = line.strip()
            safe = raw.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            if raw.endswith(':'):
                all_cmds.append(f'BT /F2 {font_sz} Tf {margin} {y} Td ({safe}) Tj ET')
            elif is_hex(raw):
                all_cmds.append(f'BT /F1 {font_sz} Tf {indent} {y} Td ({safe}) Tj ET')
            else:
                all_cmds.append(f'BT /F3 {font_sz} Tf {indent} {y} Td ({safe}) Tj ET')
            y -= line_h

    streams = []
    current = b''
    for cmd in all_cmds:
        cmd_bytes = cmd.encode()
        if len(current) + len(cmd_bytes) + 1 > max_stream and current:
            streams.append(current)
            current = cmd_bytes
        else:
            current = current + b' ' + cmd_bytes if current else cmd_bytes
    if current:
        streams.append(current)

    final_streams = []
    for s in streams:
        if len(s) <= max_stream:
            final_streams.append(s)
        else:
            blocks = []
            for m in __import__('re').finditer(rb'BT .*? ET', s):
                blocks.append(m.group())
            cur = b''
            for blk in blocks:
                if len(cur) + len(blk) + 1 > max_stream and cur:
                    final_streams.append(cur)
                    cur = blk
                else:
                    cur = cur + b' ' + blk if cur else blk
            if cur:
                final_streams.append(cur)

    n_streams = len(final_streams)

    add('header',b'%PDF-1.4\n')
    add('cat',b'1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n')
    add('pages',b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n')

    content_objs = list(range(4, 4 + n_streams))
    font_obj = 4 + n_streams
    contents_ref = ' '.join(f'{o} 0 R' for o in content_objs)
    if n_streams == 1:
        contents_str = f'{content_objs[0]} 0 R'
    else:
        contents_str = f'[{contents_ref}]'

    font_obj2 = font_obj + 1
    font_obj3 = font_obj + 2
    add('page', f'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 {page_h}]'
        f'/Contents {contents_str}/Resources<</Font<</F1 {font_obj} 0 R/F2 {font_obj2} 0 R/F3 {font_obj3} 0 R>>>>>>endobj\n'.encode())

    for i, stream in enumerate(final_streams):
        obj_num = content_objs[i]
        add(f'content{i}', f'{obj_num} 0 obj<</Length {len(stream)}>>stream\n'.encode()
            + stream + b'\nendstream endobj\n')

    add('font', f'{font_obj} 0 obj<</Type/Font/Subtype/Type1/BaseFont/Courier>>endobj\n'.encode())
    add('font2', f'{font_obj2} 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold>>endobj\n'.encode())
    add('font3', f'{font_obj3} 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n'.encode())

    n_objs = font_obj3 + 1
    xref_offset = base_offset + sum(len(p) for p in parts)
    xref = f'xref\n0 {n_objs}\n0000000000 65535 f \n'.encode()
    obj_offsets = {1: offs['cat'], 2: offs['pages'], 3: offs['page'],
                   font_obj: offs['font'], font_obj2: offs['font2'], font_obj3: offs['font3']}
    for i in range(n_streams):
        obj_offsets[content_objs[i]] = offs[f'content{i}']
    for obj_num in range(1, n_objs):
        xref += f'{obj_offsets.get(obj_num,0):010d} 00000 n \n'.encode()
    xref += f'trailer<</Size {n_objs}/Root 1 0 R>>\nstartxref\n{xref_offset}\n%%EOF\n'.encode()
    parts.append(xref)
    return b''.join(parts)

def build_zip_data(entries, vc_hint=1):
    dos_time = 0
    dos_date = 0x0021

    lfh_blob = b''
    entry_info = []
    for fname, fdata in entries:
        crc = zlib.crc32(fdata) & 0xFFFFFFFF
        rel_offset = len(lfh_blob)
        lfh = struct.pack('<IHHHHHIIIHH', 0x04034b50, 10, 0, 0, dos_time, dos_date, crc,
                          len(fdata), len(fdata), len(fname), 0) + fname + fdata
        lfh_blob += lfh
        entry_info.append((fname, crc, len(fdata), rel_offset))

    lfh_chunks = [lfh_blob[i:i+500] for i in range(0, len(lfh_blob), 500)]
    vc = vc_hint

    for _pass in range(3):
        all_items = list(lfh_chunks)
        n_data_items = len(all_items) + 1
        vc = max(1, (n_data_items + MAX_ITEMS_PER_VIN - 1) // MAX_ITEMS_PER_VIN)
        before_w = 7 + vc*41 + 1 + 9 + len(OP_RETURN_SPK)

        pos = before_w + 1
        lfh_abs_offset = pos + len(varint(len(lfh_chunks[0])))

        for chunk in lfh_chunks:
            pos += len(varint(len(chunk))) + len(chunk)
        cd_item_start = pos

        cd = b''
        for fname, crc, size, rel_off in entry_info:
            cd += struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, 10, 10, 0, 0, dos_time, dos_date,
                              crc, size, size, len(fname), 0, 0, 0, 0, 0,
                              lfh_abs_offset + rel_off) + fname

        est_item2 = cd + b'\x00' * 22
        cd_content_offset = cd_item_start + len(varint(len(est_item2)))
        eocd = struct.pack('<IHHHHII', 0x06054b50, 0, 0,
                           len(entries), len(entries), len(cd), cd_content_offset)
        eocd += struct.pack('<H', 0)
        cd_eocd = cd + eocd
        all_items.append(cd_eocd)

        data_per_vin = [all_items[i:i+MAX_ITEMS_PER_VIN]
                        for i in range(0, len(all_items), MAX_ITEMS_PER_VIN)]
        if len(data_per_vin) == vc: break
        vc = len(data_per_vin)

    return data_per_vin, vc

def _prepare_tiff(input_path, pubkey=None):
    strips, w, h = prepare_strips(input_path, None, None)
    vc = tiff_vin_count(len(strips))
    est = 0
    ok = False
    if pubkey:
        for try_vc in range(vc, vc + 4):
            try:
                layout = TiffLayout(strips, pubkey, try_vc, 0x00, w, h)
                est = layout.total_size
                vc = try_vc
                ok = True
                break
            except ValueError:
                continue
    if not ok:
        est = sum(len(s) for s in strips) + vc * 600
        if est > 60000:
            print(f"  warning: image may be too large. recommend 150x150 or smaller.")
    return {
        'width': w, 'height': h,
        'strip_count': len(strips),
        'vin_count': vc,
        'estimated_size': est,
        'grind_target': {0: 0},
    }

def _prepare_html(input_path):
    with open(input_path, 'rb') as f: data = f.read()
    data_per_vin = chunk_html(data)
    vc = len(data_per_vin)
    est = 7 + vc*41 + 1 + 9 + len(OP_RETURN_SPK) + 4
    for items in data_per_vin:
        est += len(varint(len(items)+2))
        for d in items: est += len(varint(len(d))) + len(d)
        est += 72 + 200
    return {
        'vin_count': vc,
        'estimated_size': est,
        'grind_target': {},
    }

def _prepare_pdf(input_path):
    data_per_vin = _pdf_data_per_vin(input_path)
    vc = len(data_per_vin)
    est = 7 + vc*41 + 1 + 9 + len(OP_RETURN_SPK) + 4
    for items in data_per_vin:
        est += len(varint(len(items)+2))
        for d in items: est += len(varint(len(d))) + len(d)
        est += 72 + 200
    return {
        'vin_count': vc,
        'estimated_size': est,
        'grind_target': {},
    }

def _prepare_zip(input_path):
    entries = _load_zip_entries(input_path)
    data_per_vin, vc = build_zip_data(entries)
    est = 7 + vc*41 + 1 + 9 + len(OP_RETURN_SPK) + 4
    for items in data_per_vin:
        est += len(varint(len(items)+2))
        for d in items: est += len(varint(len(d))) + len(d)
        est += 72 + 200
    return {
        'vin_count': vc,
        'estimated_size': est,
        'grind_target': {},
    }

def _load_zip_entries(input_path):
    if input_path.endswith('.zip'):
        import zipfile
        with zipfile.ZipFile(input_path) as zf:
            return [(info.filename.encode(), zf.read(info.filename)) for info in zf.infolist()]
    else:
        with open(input_path, 'rb') as f: data = f.read()
        return [(os.path.basename(input_path).encode(), data)]

def _build_tiff(state):
    input_path = state['input_path']
    w, h = state['width'], state['height']
    strips, w, h = prepare_strips(input_path, w, h)
    privkey = bytes.fromhex(state['privkey_hex'])
    pubkey = bytes.fromhex(state['pubkey_hex'])
    vc = state['vin_count']
    txid = state['funding_txid']
    values = state['funding_values']
    raw_tx, layout = build_tiff_tx(strips, txid, values, privkey, pubkey, vc, w, h)
    return raw_tx

def _build_html(state):
    with open(state['input_path'], 'rb') as f: data = f.read()
    data_per_vin = chunk_html(data)
    privkey = bytes.fromhex(state['privkey_hex'])
    pubkey = bytes.fromhex(state['pubkey_hex'])
    return build_tx(STD_VERSION, data_per_vin, pubkey, privkey,
                    state['funding_txid'], state['funding_values'])

def _adjust_pdf_offsets(raw_pdf, base_offset):
    return _adjust_pdf_offsets_with_varints(raw_pdf, base_offset, len(raw_pdf)+1, [0])

def _adjust_pdf_offsets_with_varints(raw_pdf, before_w, chunk_boundaries, overhead_at):
    import re

    def file_offset(raw_off):
        for ci in range(len(chunk_boundaries)-1, -1, -1):
            if raw_off >= chunk_boundaries[ci]:
                return before_w + raw_off + overhead_at[ci]
        return before_w + raw_off + overhead_at[0]

    xref_match = re.search(rb'xref\n0 (\d+)\n', raw_pdf)
    if not xref_match:
        raise ValueError("xref not found in PDF")
    n_objs = int(xref_match.group(1))
    xref_start = xref_match.end()

    new_pdf = bytearray(raw_pdf[:xref_match.start()])
    new_pdf += f'xref\n0 {n_objs}\n'.encode()
    pos = xref_start
    for i in range(n_objs):
        line = raw_pdf[pos:pos+20]
        offset = int(line[:10])
        gen = line[11:16]
        status = line[17:18]
        if i == 0:
            new_pdf += line
        else:
            new_pdf += f'{file_offset(offset):010d} '.encode() + gen + b' ' + status + b' \n'
        pos += 20

    trailer_start = raw_pdf.find(b'trailer', pos)
    trailer = raw_pdf[trailer_start:]
    startxref_match = re.search(rb'startxref\n(\d+)\n', trailer)
    old_startxref = int(startxref_match.group(1))
    new_trailer = trailer[:startxref_match.start()]
    new_trailer += f'startxref\n{file_offset(old_startxref)}\n'.encode()
    new_trailer += b'%%EOF\n'
    new_pdf += new_trailer
    return bytes(new_pdf)

def chunk_pdf(data, chunk_size=496):
    import re
    safe_points = set()
    for m in re.finditer(rb'endobj\n', data):
        safe_points.add(m.end())
    safe_points = sorted(safe_points)

    chunks = []
    pos = 0
    while pos < len(data):
        end = min(pos + chunk_size, len(data))
        if end < len(data):
            best = None
            for sp in safe_points:
                if pos < sp <= end:
                    best = sp
            if best:
                end = best
        chunk = data[pos:end]
        if end < len(data):
            chunk += b'\n%'
        if pos > 0:
            chunk = b'\n' + chunk
        chunks.append(chunk)
        pos = end
    vins = []
    for i in range(0, len(chunks), MAX_ITEMS_PER_VIN):
        vins.append(chunks[i:i+MAX_ITEMS_PER_VIN])
    return vins

def _read_pdf_lines(input_path):
    if input_path.endswith('.pdf'):
        try:
            import PyPDF2
            with open(input_path,'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = '\n'.join(p.extract_text() for p in reader.pages)
        except ImportError:
            text = subprocess.run(['strings', input_path], capture_output=True, text=True).stdout
        return text.strip().split('\n')
    else:
        with open(input_path,'r') as f: return f.read().strip().split('\n')

def _pdf_data_per_vin(input_path):
    import re
    with open(input_path, 'rb') as f:
        pdf = f.read()

    safe_points = [0]
    for m in re.finditer(rb'endobj\n', pdf):
        safe_points.append(m.end())
    safe_points.append(len(pdf))

    raw_chunks = []
    pos = 0
    while pos < len(pdf):
        best = pos
        for sp in safe_points:
            if sp <= pos: continue
            if sp - pos <= MAX_ITEM - 3:
                best = sp
            else:
                break
        if best == pos:
            best = min(pos + MAX_ITEM - 3, len(pdf))
        raw_chunks.append(pdf[pos:best])
        pos = best

    n_chunks = len(raw_chunks)
    vc = max(1, (n_chunks + MAX_ITEMS_PER_VIN - 1) // MAX_ITEMS_PER_VIN)
    before_w = 7 + vc*41 + 1 + 9 + len(OP_RETURN_SPK)
    item_count_vi = len(varint(n_chunks + 2))

    final_sizes = []
    for ci in range(n_chunks):
        sz = len(raw_chunks[ci])
        if ci < n_chunks - 1: sz += 2
        if ci > 0: sz += 1
        final_sizes.append(sz)

    file_pos = before_w + item_count_vi
    chunk_pdf_starts = []
    for ci in range(n_chunks):
        vi = len(varint(final_sizes[ci]))
        prefix = 1 if ci > 0 else 0
        chunk_pdf_starts.append(file_pos + vi + prefix)
        file_pos += vi + final_sizes[ci]

    cb = [0]
    for c in raw_chunks:
        cb.append(cb[-1] + len(c))

    def pdf_to_file(pdf_off):
        for ci in range(n_chunks-1, -1, -1):
            if pdf_off >= cb[ci]:
                return chunk_pdf_starts[ci] + (pdf_off - cb[ci])
        return chunk_pdf_starts[0] + pdf_off

    xref_match = re.search(rb'xref\n0 (\d+)\n', pdf)
    n_objs = int(xref_match.group(1))
    xref_pos_start = xref_match.end()

    new_pdf = bytearray(pdf[:xref_match.start()])
    new_pdf += f'xref\n0 {n_objs}\n'.encode()
    xpos = xref_pos_start
    for i in range(n_objs):
        line = pdf[xpos:xpos+20]
        offset = int(line[:10])
        gen = line[11:16]
        status = line[17:18]
        if i == 0:
            new_pdf += line
        else:
            new_pdf += f'{pdf_to_file(offset):010d} '.encode() + gen + b' ' + status + b' \n'
        xpos += 20

    trailer_start = pdf.find(b'trailer', xpos)
    trailer = pdf[trailer_start:]
    sxref_match = re.search(rb'startxref\n(\d+)\n', trailer)
    old_sxref = int(sxref_match.group(1))
    new_trailer = trailer[:sxref_match.start()]
    new_trailer += f'startxref\n{pdf_to_file(old_sxref)}\n'.encode()
    new_trailer += b'%%EOF\n'
    new_pdf += new_trailer
    pdf_fixed = bytes(new_pdf)

    final_chunks = []
    pos = 0
    for ci in range(n_chunks):
        if ci < n_chunks - 1:
            chunk = pdf_fixed[pos:pos+len(raw_chunks[ci])]
            pos += len(raw_chunks[ci])
        else:
            chunk = pdf_fixed[pos:]
        if ci < n_chunks - 1:
            chunk += b'\n%'
        if ci > 0:
            chunk = b'\n' + chunk
        final_chunks.append(chunk)

    data_per_vin = []
    for i in range(0, len(final_chunks), MAX_ITEMS_PER_VIN):
        data_per_vin.append(final_chunks[i:i+MAX_ITEMS_PER_VIN])

    return data_per_vin

def _build_pdf(state):
    data_per_vin = _pdf_data_per_vin(state['input_path'])
    privkey = bytes.fromhex(state['privkey_hex'])
    pubkey = bytes.fromhex(state['pubkey_hex'])
    return build_tx(STD_VERSION, data_per_vin, pubkey, privkey,
                    state['funding_txid'], state['funding_values'])

def _build_zip(state):
    entries = _load_zip_entries(state['input_path'])
    data_per_vin, vc = build_zip_data(entries)
    privkey = bytes.fromhex(state['privkey_hex'])
    pubkey = bytes.fromhex(state['pubkey_hex'])
    return build_tx(STD_VERSION, data_per_vin, pubkey, privkey,
                    state['funding_txid'], state['funding_values'])

def cmd_prepare(args):
    fmt = args.format
    input_path = os.path.abspath(args.input)
    if not os.path.exists(input_path):
        sys.exit(f"input file not found: {input_path}")

    print(f"=== prepare ({fmt}) ===")
    print(f"  input: {input_path}")

    privkey, pubkey = keygen()

    if fmt == 'tiff':
        prep = _prepare_tiff(input_path, pubkey)
    else:
        prep = {'html': _prepare_html, 'pdf': _prepare_pdf,
                'zip': _prepare_zip}[fmt](input_path)

    vc = prep['vin_count']
    vp = 10000
    total_fund = vp * vc + 500

    print(f"  format: {fmt}")
    if fmt == 'tiff':
        print(f"  image size: {prep['width']}x{prep['height']}")
        print(f"  strips: {prep['strip_count']}")
    print(f"  vins: {vc}")
    print(f"  estimated tx size: {prep['estimated_size']:,} bytes")
    print(f"  required funds: {total_fund:,} sats ({total_fund/1e8:.8f} BTC)")

    state = {
        'format': fmt,
        'network': args.network,
        'input_path': input_path,
        'privkey_hex': privkey.hex(),
        'pubkey_hex': pubkey.hex(),
        'vin_count': vc,
        'value_per_vin': vp,
        'estimated_size': prep['estimated_size'],
        'grind_target': prep['grind_target'],
    }
    if args.wallet:
        state['wallet'] = args.wallet
    if fmt == 'tiff':
        state['width'] = prep['width']
        state['height'] = prep['height']

    sf = args.output or f'state_{fmt}.json'
    with open(sf, 'w') as f:
        json.dump(state, f, indent=2)
    print(f"\n  state saved: {sf}")
    print(f"\n  next: python3 inscribe.py fund {sf}")

def cmd_fund(args):
    with open(args.state_file) as f:
        state = json.load(f)

    fmt = state['format']
    net = state['network']
    wallet = state.get('wallet')
    pubkey = bytes.fromhex(state['pubkey_hex'])
    vc = state['vin_count']
    vp = state['value_per_vin']
    grind = {int(k): v for k, v in state['grind_target'].items()}

    print(f"=== fund ({fmt}) ===")

    if fmt == 'tiff':
        strips, w, h = prepare_strips(state['input_path'], state['width'], state['height'])
        target_byte = grind.get(0, 0x00)
        layout = None
        for try_vc in range(vc, vc + 4):
            try:
                layout = TiffLayout(strips, pubkey, try_vc, target_byte, w, h)
                if try_vc != vc:
                    print(f"  adjusted vins from {vc} to {try_vc}")
                    vc = try_vc
                    state['vin_count'] = vc
                break
            except ValueError:
                continue
        if layout is None:
            sys.exit("layout failed: reduce image size")
        wscripts = layout.get_witness_scripts()
    else:
        if fmt == 'html':
            with open(state['input_path'], 'rb') as f: data = f.read()
            data_per_vin = chunk_html(data)
        elif fmt == 'pdf':
            data_per_vin = _pdf_data_per_vin(state['input_path'])
        elif fmt == 'zip':
            entries = _load_zip_entries(state['input_path'])
            data_per_vin, _ = build_zip_data(entries)

        wscripts = [witness_script(pubkey, items) for items in data_per_vin]

    addrs = [p2wsh_addr(ws, net) for ws in wscripts]
    print(f"  P2WSH addresses: {len(addrs)}")
    for i, a in enumerate(addrs):
        print(f"    vin[{i}]: {a}")

    utxos = json.loads(cli(["listunspent"], net, wallet))
    utxo = next((u for u in utxos if int(u['amount']*1e8) >= vp*vc+2000 and u['spendable']), None)
    if not utxo:
        sys.exit("no suitable UTXO")

    ut, uv, ua = utxo['txid'], utxo['vout'], int(round(utxo['amount']*1e8))
    ca = cli(["getnewaddress"], net, wallet)
    base = ua - vp*vc - 500
    print(f"  UTXO: {ut}:{uv} ({ua} sats)")

    outs = [{a: f"{vp/1e8:.8f}"} for a in addrs] + [{ca: f"{base/1e8:.8f}"}]
    raw = cli(["createrawtransaction", json.dumps([{"txid": ut, "vout": uv}]), json.dumps(outs)], net, wallet)
    rb = bytearray(bytes.fromhex(raw))
    cv = struct.pack('<Q', base)
    cp = bytes(rb).rfind(cv)
    if cp < 0:
        sys.exit("change not found in raw tx")

    print(f"  grinding...")
    t0 = time.time()
    for n in range(200000):
        nc = base - n
        if nc < 546:
            sys.exit("reached dust limit")
        struct.pack_into('<Q', rb, cp, nc)
        tid = hash256(bytes(rb))[::-1]
        ti2 = tid[::-1]
        if all(ti2[int(p)] == t for p, t in grind.items()):
            td = tid.hex()
            el = time.time() - t0
            print(f"  match! ({n+1} tries, {el:.1f}s)")
            print(f"  Funding txid: {td}")
            s = json.loads(cli(["signrawtransactionwithwallet", bytes(rb).hex()], net, wallet))
            cli(["sendrawtransaction", s['hex']], net, wallet)
            if net == "regtest":
                cli(["generatetoaddress", "1", ca], net, wallet)
                print(f"  block generated")
            else:
                print(f"  broadcast (wait for confirmation)")

            state['funding_txid'] = td
            state['funding_values'] = [vp] * vc
            with open(args.state_file, 'w') as f:
                json.dump(state, f, indent=2)
            print(f"\n  state updated: {args.state_file}")
            print(f"\n  next: python3 inscribe.py build {args.state_file}")
            return
        if n % 10000 == 0 and n > 0:
            print(f"    {n}... ({n/(time.time()-t0):.0f}/s)")

    sys.exit("grinding failed")

def cmd_build(args):
    with open(args.state_file) as f:
        state = json.load(f)

    fmt = state['format']
    if 'funding_txid' not in state:
        sys.exit("run fund first")

    print(f"=== build ({fmt}) ===")
    print(f"  Funding txid: {state['funding_txid']}")

    builder = {'tiff': _build_tiff, 'html': _build_html,
               'pdf': _build_pdf, 'zip': _build_zip}[fmt]
    raw_tx = builder(state)

    out = args.output or f'output.{fmt}'
    with open(out, 'wb') as f:
        f.write(raw_tx)

    state['raw_tx_hex'] = raw_tx.hex()
    state['output_file'] = out
    with open(args.state_file, 'w') as f:
        json.dump(state, f, indent=2)

    print(f"  saved: {out} ({len(raw_tx):,} bytes)")
    print(f"  state updated: {args.state_file}")

    if fmt == 'tiff':
        try:
            img = Image.open(out)
            print(f"  TIFF verify: OK ({img.size[0]}x{img.size[1]})")
        except Exception as e:
            print(f"  TIFF verify: NG ({e})")

    print(f"\n  next: python3 inscribe.py broadcast {args.state_file}")

def cmd_broadcast(args):
    with open(args.state_file) as f:
        state = json.load(f)

    if 'raw_tx_hex' not in state:
        sys.exit("run build first")

    fmt = state['format']
    net = state['network']
    wallet = state.get('wallet')

    print(f"=== broadcast ({fmt}) ===")
    print(f"  network: {net}")
    print(f"  tx size: {len(state['raw_tx_hex'])//2:,} bytes")

    if net == 'mainnet':
        print(f"\n  *** sending to mainnet. this cannot be undone. ***")
        confirm = input("  continue? (yes/no): ")
        if confirm.lower() != 'yes':
            print("  aborted.")
            return

    try:
        txid = cli(["sendrawtransaction", state['raw_tx_hex']], net, wallet)
        print(f"  broadcast ok!")
        print(f"  TXID: {txid}")
        if net == "regtest":
            ca = cli(["getnewaddress"], net, wallet)
            cli(["generatetoaddress", "1", ca], net, wallet)
            print(f"  block generated")
    except RuntimeError as e:
        print(f"  error: {e}")

def main():
    p = argparse.ArgumentParser(description='Bitcoin Polyglot Tx Builder')
    sub = p.add_subparsers(dest='cmd')

    sp = sub.add_parser('prepare', help='analyze input, generate keys, save state')
    sp.add_argument('format', choices=['tiff', 'html', 'pdf', 'zip'])
    sp.add_argument('input', help='input file')
    sp.add_argument('--network', default='regtest')
    sp.add_argument('--wallet', help='bitcoin-cli -rpcwallet name')
    sp.add_argument('-o', '--output', help='state file name')

    sf = sub.add_parser('fund', help='fund P2WSH + grind txid')
    sf.add_argument('state_file')

    sb = sub.add_parser('build', help='build and sign tx')
    sb.add_argument('state_file')
    sb.add_argument('-o', '--output', help='output file name')

    sc = sub.add_parser('broadcast', help='broadcast')
    sc.add_argument('state_file')

    args = p.parse_args()
    if args.cmd == 'prepare': cmd_prepare(args)
    elif args.cmd == 'fund': cmd_fund(args)
    elif args.cmd == 'build': cmd_build(args)
    elif args.cmd == 'broadcast': cmd_broadcast(args)
    else: p.print_help()

if __name__ == '__main__':
    main()
