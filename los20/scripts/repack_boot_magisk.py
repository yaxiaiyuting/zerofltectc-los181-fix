#!/usr/bin/env python3
"""把打好的 Magisk ramdisk 装回 boot 镜像（保留内核与三星 DHTB 设备树表）

为什么需要这个脚本：
  Magisk 自带的 `magiskboot repack` 无法处理三星的 DHTB 设备树封装
  （`magiskboot dtb extra test` 会失败 → boot_patch.sh abort），
  所以我们在设备上用 magiskboot 只做 ramdisk 补丁，打包交回这个脚本。

当前 boot 分区布局（三星 legacy，header_version=0，page=2048）：
  0x0000  ANDROID! 头（10 个 u32）
  0x0030  name[512]  ← 三星把 "buildvariant=userdebug" 塞在这
  0x0800  kernel
  ...     ramdisk
  ...     second (0)
  ...     DHTB 设备树表 + DTB 条目 + SEANDROIDENFORCE

用法: repack_boot_magisk.py <原 boot.img> <新 ramdisk.cpio> <输出 boot.img>
"""
import lzma
import struct
import sys

MAGIC = b'ANDROID!'
DHTB = 0x48425444
SEANDROID = b'SEANDROIDENFORCE'


def parse(d):
    assert d[:8] == MAGIC, '不是 Android boot 镜像'
    (ks, ka, rs, ra, ss, sa, ta, ps, f40, f44) = struct.unpack_from('<10I', d, 8)
    return dict(ks=ks, ka=ka, rs=rs, ra=ra, ss=ss, sa=sa, ta=ta, ps=ps, f40=f40, f44=f44)


def main():
    src, new_ramdisk_path, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    d = open(src, 'rb').read()
    h = parse(d)
    ps = h['ps']
    pg = lambda n: (n + ps - 1) // ps

    o = ps
    kernel = d[o:o + h['ks']]; o += pg(h['ks']) * ps
    old_ram = d[o:o + h['rs']]; o += pg(h['rs']) * ps
    second = d[o:o + h['ss']]; o += pg(h['ss']) * ps
    tail = d[o:]
    print(f'原镜像: kernel={len(kernel):,}  ramdisk={len(old_ram):,}  tail={len(tail):,}  page={ps}')

    # 检查 tail 是 DHTB 表
    magic, ver, cnt = struct.unpack_from('<3I', tail, 0)
    assert magic == DHTB, f'tail 不是 DHTB 表: {magic:#x}'
    print(f'DHTB v{ver} entries={cnt}  → 原样保留')

    # 新 ramdisk：cpio → xz 压缩（内核 initramfs 支持 xz）
    cpio = open(new_ramdisk_path, 'rb').read()
    print(f'新 ramdisk cpio: {len(cpio):,} 字节')
    ram_xz = lzma.compress(cpio, format=lzma.FORMAT_XZ, preset=6)
    print(f'   xz 压缩后: {len(ram_xz):,} 字节')

    # 重新打包
    out = bytearray()
    out += MAGIC
    out += struct.pack('<10I', h['ks'], h['ka'], len(ram_xz), h['ra'],
                       h['ss'], h['sa'], h['ta'], ps, h['f40'], h['f44'])
    out += d[48:560].ljust(512, b'\x00')          # 原样保留 name[512]
    if len(out) % ps:
        out += b'\x00' * (ps - len(out) % ps)
    out += kernel + b'\x00' * ((-h['ks']) % ps)
    out += ram_xz + b'\x00' * ((-len(ram_xz)) % ps)
    if second:
        out += second + b'\x00' * ((-h['ss']) % ps)
    out += tail
    open(dst, 'wb').write(bytes(out))
    print(f'✅ 写出 {dst}  {len(out):,} 字节')

    # 自检
    d2 = open(dst, 'rb').read()
    h2 = parse(d2)
    assert h2['ks'] == h['ks'] and h2['rs'] == len(ram_xz)
    o2 = ps + pg(h2['ks']) * ps
    got = d2[o2:o2 + h2['rs']]
    assert lzma.decompress(got) == cpio, 'ramdisk 回读不一致'
    t2 = d2[o2 + pg(h2['rs']) * ps + pg(h2['ss']) * ps:]
    assert t2 == tail, 'DTB 表不一致'
    m2, v2, c2 = struct.unpack_from('<3I', t2, 0)
    print(f'✅ 自检通过：ramdisk 可解压且与输入一致；DTB 表逐字节一致（magic={m2:#x} entries={c2}）')


if __name__ == '__main__':
    main()
