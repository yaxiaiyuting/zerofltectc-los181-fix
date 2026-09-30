#!/usr/bin/env python3
"""用「ROM 原版 DTB」替换自编译 boot.img 里的 DTB 条目（回退方案用）

场景：自编译内核的 DTS 与 ROM 包里的 DTB 有几处结构差异
      （hmp 节点、input_booster 位置、bootargs 内容等）。
      万一实机出现显示/音频/相机等硬件异常，可以用 ROM 的 DTB（已被证明可用）
      配上自编译内核，把变量收敛到"只有 eBPF 回移"这一个改动。

用法: swap_dtb.py <自编译 boot.img> <ROM boot.img> <输出 boot.img>
"""
import struct
import sys

DHTB_MAGIC = 0x48425444
PAGE = 2048


def unpack(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'ANDROID!'
    f = struct.unpack_from('<10I', d, 8)
    ps = f[7]
    pg = lambda n: (n + ps - 1) // ps
    o = ps
    pk = pg(f[0]) * ps
    pr = pg(f[2]) * ps
    ps2 = pg(f[4]) * ps
    return d, f, d[o:o + f[0]], d[o + pk:o + pk + f[2]], d[o + pk + pr:o + pk + pr + f[4]], d[o + pk + pr + ps2:]


def entries(tail):
    magic, ver, cnt = struct.unpack_from('<3I', tail, 0)
    assert magic == DHTB_MAGIC, f'不是 DHTB 表: {magic:#x}'
    out = []
    for i in range(cnt):
        b = 0x20 + i * 0x20
        off, sz, f8, hw, f10, f14, f18, f1c = struct.unpack_from('<8I', tail, b)
        out.append(dict(idx=i, hdr=b, off=off, size=sz, hw=hw,
                        raw=struct.unpack_from('<8I', tail, b)))
    return ver, cnt, out


def main():
    mine, rom, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    dm, fm, km, rm, sm, tm = unpack(mine)
    dr, fr, kr, rr, sr, tr = unpack(rom)
    vm, cm, em = entries(tm)
    vr, cr, er = entries(tr)
    print(f'自编译 boot: entries={cm}  ' + ' '.join(f'[{e["idx"]}]sz={e["size"]:,}' for e in em))
    print(f'ROM   boot: entries={cr}  ' + ' '.join(f'[{e["idx"]}]sz={e["size"]:,}' for e in er))
    assert cm == cr, '条目数不同，无法直接替换'
    for a, b in zip(em, er):
        assert a['size'] == b['size'], f'条目 {a["idx"]} 大小不同'
        assert a['hw'] == b['hw'], f'条目 {a["idx"]} hw_rev 不同'

    # 用 ROM 的 DTB 内容重建 tail（表头取自编译的，条目偏移/大小不变）
    head = bytearray(tm[:em[0]['off']])
    new_tail = bytes(head)
    for e in er:
        new_tail += tr[e['off']:e['off'] + e['size']]

    out = bytearray()
    out += dm[:PAGE]                       # 原始 2048 字节 boot 头
    out += km + b'\x00' * ((-fm[0]) % fm[7])
    out += rm + b'\x00' * ((-fm[2]) % fm[7])
    if sm:
        out += sm + b'\x00' * ((-fm[4]) % fm[7])
    out += new_tail
    # 保留 SEANDROIDENFORCE（若原文件末尾有）
    s = dm.rfind(b'SEANDROIDENFORCE')
    if s >= 0 and s not in range(len(out) - 64, len(out)):
        out += b'SEANDROIDENFORCE'
    open(dst, 'wb').write(bytes(out))
    print(f'✅ 写出 {dst}  {len(out):,} 字节')

    # 回读校验
    d2, f2, k2, r2, s2, t2 = unpack(dst)
    assert k2 == km and r2 == rm, 'kernel/ramdisk 不一致'
    v2, c2, e2 = entries(t2)
    for a, b in zip(e2, er):
        got = t2[a['off']:a['off'] + a['size']]
        want = tr[b['off']:b['off'] + b['size']]
        assert got == want, f'条目 {a["idx"]} DTB 替换失败'
    print('✅ 回读校验通过：两个 DTB 条目均来自 ROM 原版')


if __name__ == '__main__':
    main()
