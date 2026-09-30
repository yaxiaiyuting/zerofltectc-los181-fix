#!/usr/bin/env python3
"""线性、无 import 的零fluff实现：给 zeroflte boot.img 打触摸修复（DTB 节点搬移）"""
import hashlib
import os
import re
import struct
import subprocess
import sys
import tempfile

SRC = sys.argv[1]
DST = sys.argv[2]
WORK = tempfile.mkdtemp(prefix='fix-')
print('工作目录', WORK)


def md5(b):
    return hashlib.md5(b).hexdigest()


raw = open(SRC, 'rb').read()
assert raw[:8] == b'ANDROID!'
(kern_sz, kern_addr, ram_sz, ram_addr, sec_sz, sec_addr, tags, page, f40, f44) = \
    struct.unpack_from('<10I', raw, 8)
print(f'boot: kernel={kern_sz:,} ramdisk={ram_sz:,} page={page}')

pg = lambda n: (n + page - 1) // page
o = page
kern = raw[o:o + kern_sz]; o += pg(kern_sz) * page
ram = raw[o:o + ram_sz]; o += pg(ram_sz) * page
sec = raw[o:o + sec_sz]; o += pg(sec_sz) * page
tail = raw[o:]
print(f'tail={len(tail):,}  md5={md5(tail)}')

# --- DHTB 表 ---
dm, dver, dcnt, df12, df16 = struct.unpack_from('<5I', tail, 0)
assert dm == 0x48425444
ents = []
for i in range(dcnt):
    b = 0x20 + i * 0x20
    off, sz, f8, hwrev, f10, f14, f18, f1c = struct.unpack_from('<8I', tail, b)
    ents.append((i, off, sz, hwrev, b))
    print(f'  [{i}] hdr_off={b:#x} off={off:#x} size={sz:,} hw_rev={hwrev}')
i0, off0, sz0, hw0, b0 = ents[0]
blob0 = tail[off0:off0 + sz0]
open(f'{WORK}/dtb0.dtb', 'wb').write(blob0)
print(f'原始 dtb0: {len(blob0):,} md5={md5(blob0)}')

# --- 反编译 ---
dts = f'{WORK}/a.dts'
r = subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', '-o', dts, f'{WORK}/dtb0.dtb'],
                   capture_output=True)
assert r.returncode == 0, r.stderr[-500:]
L = open(dts).read().splitlines()
print(f'反编译 OK，{len(L)} 行')


def node_range(lines, name):
    pat = re.compile(r'^\t+' + re.escape(name) + r'\s*\{')
    s = next((i for i, l in enumerate(lines) if pat.match(l)), None)
    if s is None:
        return None, None
    d = 0
    for j in range(s, len(lines)):
        d += lines[j].count('{') - lines[j].count('}')
        if d == 0 and j > s:
            return s, j
    return s, None


s_name = next((re.match(r'^\t+(s2mpb02@[0-9a-fA-F]+)\s*\{', l).group(1)
               for l in L if re.match(r'^\t+(s2mpb02@[0-9a-fA-F]+)\s*\{', l)), None)
assert s_name, '找不到 s2mpb02'
ss, se = node_range(L, s_name)
block = L[ss:se + 1]
print(f'源节点 {s_name}: 行 {ss + 1}..{se + 1}（{len(block)} 行）')

ds, de = node_range(L, 'hsi2c@13670000')
assert ds is not None and de is not None, '找不到 hsi2c@13670000 节点定义'
print(f'目标节点 hsi2c@13670000: 行 {ds + 1}..{de + 1}')

newL = L[:ss] + L[se + 1:]
if de > ss:
    de -= len(block)
newL = newL[:de] + block + newL[de:]
open(f'{WORK}/b.dts', 'w').write('\n'.join(newL) + '\n')

# --- 重编译 ---
newdtb = f'{WORK}/dtb0.new.dtb'
r = subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', newdtb, f'{WORK}/b.dts'],
                   capture_output=True)
assert r.returncode == 0, r.stderr[-800:]
nb = open(newdtb, 'rb').read()
print(f'新 dtb0 : {len(nb):,} md5={md5(nb)}')

# --- 校验：新 dtb0 里 s2mpb02 的父节点 ---
v = f'{WORK}/v.dts'
subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', '-o', v, newdtb], capture_output=True)
VL = open(v).read().splitlines()
vs, ve = node_range(VL, s_name)
assert vs is not None
parent = next(VL[i].strip().split()[0] for i in range(vs - 1, -1, -1)
              if re.match(r'^\t[^\t]+\s*\{', VL[i]))
assert parent == 'hsi2c@13670000', f'父节点错误: {parent}'
ok_src, ok_se = node_range(VL, 'hsi2c@14E60000')
assert s_name not in '\n'.join(VL[ok_src:ok_se + 1]), '源总线里还有 s2mpb02'
print(f'✅ 校验通过：{s_name} 的父节点 = {parent}')

# --- 重建 tail ---
# 布局: [表头+条目 0x00..0x60) [填充 0x60..blob0_off) [blob0] [blob1] ...
# 注意必须保留 blob0 之前的填充（原为 0x800-0x60=1952 字节 + 32 字节对齐填充）
head = bytearray(tail[:off0])                 # 表头 + 条目 + 到 blob0 的填充
assert len(head) == off0, f'表头区长度异常 {len(head)} != {off0}'
struct.pack_into('<II', head, b0, off0, len(nb))
pad = (-len(nb)) % page
newtail = bytes(head) + nb + b'\x00' * pad
for (i, off, sz, hw, hb) in ents[1:]:
    newtail += tail[off:off + sz]
print(f'新 tail : {len(newtail):,} md5={md5(newtail)}')

# --- 打包 ---
buf = bytearray()
buf += b'ANDROID!'
buf += struct.pack('<10I', kern_sz, kern_addr, ram_sz, ram_addr, sec_sz, sec_addr,
                   tags, page, f40, f44)
buf += raw[48:560].ljust(512, b'\x00')
buf += b'\x00' * ((-len(buf)) % page)
buf += kern + b'\x00' * ((-kern_sz) % page)
buf += ram + b'\x00' * ((-ram_sz) % page)
if sec:
    buf += sec + b'\x00' * ((-sec_sz) % page)
buf += newtail
with open(DST, 'wb') as f:
    f.write(bytes(buf))
    f.flush()
    os.fsync(f.fileno())
print(f'✅ 写出 {DST}  {len(buf):,} 字节  md5={md5(bytes(buf))}')

# --- 独立回读校验（全新读取，避免任何缓存） ---
chk = open(DST, 'rb').read()
(k2, ka2, r2, ra2, s2, sa2, t2, p2, g2, h2) = struct.unpack_from('<10I', chk, 8)
o2 = p2
o2 += pg(k2) * p2
o2 += pg(r2) * p2
o2 += pg(s2) * p2
tail2 = chk[o2:]
assert tail2 == newtail, '回读 tail 不一致'
dm2, dv2, dc2, _, _ = struct.unpack_from('<5I', tail2, 0)
e0_2 = struct.unpack_from('<8I', tail2, 0x20)
assert e0_2[1] == len(nb), f'回读 dtb0 长度不符 {e0_2[1]} != {len(nb)}'
got = tail2[e0_2[0]:e0_2[0] + e0_2[1]]
assert got == nb, f'回读 dtb0 内容不一致 md5={md5(got)} vs {md5(nb)}'
print(f'✅ 回读校验通过：dtb0 {len(got):,} 字节 md5={md5(got)}')
print(f'   中间文件保留在 {WORK}')
