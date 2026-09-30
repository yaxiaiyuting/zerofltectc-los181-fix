#!/usr/bin/env bash
# /data 全量备份（在 /sdcard 上分卷打包 → adb pull 逐卷拉取）
#
# 踩坑记录（本机实测）：
#   1. `adb exec-out` 对 >200MB 的流会静默截断（设备侧 rc 仍为 0）
#      实测：dd 28GB→233MB、tar→29MB、cpio→93MB
#   2. TWRP 的 /tmp 是 tmpfs，只有 1.3GB → 归档不能放 /tmp（写满即失败）
#   3. TWRP 的 toybox tar 遇到 unix socket 会报 "unknown file type" 并中断 → 改用 cpio
#   4. /data/swapfile 是 8GB 交换文件（Magisk swap 模块），必须排除
#   ⇒ 方案：cpio+gzip → split 分卷写到 /sdcard（与 /data 同一分区，14GB 可用）
#           → 逐卷 adb pull（实测可靠）→ 主机合并 → 流式解压自检
set +u
OUTDIR=/home/duanjb666/deepseek/G9209-fix/los20-work/backup
DEV=/sdcard/databk
CHUNK=700000000                   # 700 MB/卷
LOG="$OUTDIR/backup-pull.log"
mkdir -p "$OUTDIR"
: > "$LOG"
say() { echo "$*" | tee -a "$LOG"; }

say "════════ $(date '+%F %T') /data 分卷备份 ════════"
adb devices | tail -n +2 | tee -a "$LOG"

say "① 设备侧打包并分卷（排除 swapfile 与 socket）"
adb shell "rm -rf $DEV; mkdir -p $DEV"
adb shell "cd /data && find . -xdev ! -type s ! -path './swapfile' | cpio -o -H newc 2>/dev/null | gzip -1 | split -b $CHUNK - $DEV/part-" 2>&1 | tee -a "$LOG"
adb shell "ls -la $DEV/" 2>&1 | tail -n +2 | tee -a "$LOG"

NP=$(adb shell "ls $DEV/part-* 2>/dev/null | wc -l" | tr -d '\r\n')
say "   共 $NP 卷"
if [ "${NP:-0}" -lt 1 ]; then say "❌ 没有产出分卷"; exit 1; fi

say ""
say "② 逐卷 pull"
rm -f "$OUTDIR"/data.part-*
i=0
for p in $(adb shell "ls $DEV/part-*" | tr -d '\r'); do
  i=$((i+1))
  n=$(basename "$p")
  printf "   [%d/%d] %s ... " "$i" "$NP" "$n" | tee -a "$LOG"
  adb pull "$p" "$OUTDIR/data.part-$n" > /tmp/pull.out 2>&1
  sz=$(stat -c%s "$OUTDIR/data.part-$n" 2>/dev/null || echo 0)
  echo "$((sz/1024/1024)) MB" | tee -a "$LOG"
done

say ""
say "③ 合并"
rm -f "$OUTDIR/data-los181.cpio.gz"
cat "$OUTDIR"/data.part-* > "$OUTDIR/data-los181.cpio.gz"
rm -f "$OUTDIR"/data.part-*
MSZ=$(stat -c%s "$OUTDIR/data-los181.cpio.gz")
DSZ=$(adb shell "cat $DEV/part-* | wc -c" | tr -d '\r\n')
say "   合并后 $MSZ 字节 / 设备侧合计 $DSZ 字节"
if [ "$MSZ" = "$DSZ" ]; then say "   ✅ 大小一致"; else say "   ❌ 大小不一致"; fi

say ""
say "④ 完整性自检（流式解压，不落盘）"
if gzip -dc "$OUTDIR/data-los181.cpio.gz" 2>/dev/null | cpio -t --quiet > /tmp/cpio-list.txt 2>/tmp/cpio-err.txt; then
  say "   ✅ 归档可完整解压，$(wc -l < /tmp/cpio-list.txt) 个条目"
  say "   顶层条目：$(awk -F/ '{print $2}' /tmp/cpio-list.txt | sort -u | tr '\n' ' ')"
  say "   ---- 关键内容抽查 ----"
  for p in "./app/" "./data/" "./media/0/" "./system/users" "./misc/keystore" "./user_de/" "./dalvik-cache/" "./local/"; do
    printf "   %-24s %s 条\n" "$p" "$(grep -c -- "^${p}" /tmp/cpio-list.txt)" | tee -a "$LOG"
  done
else
  say "   ❌ 归档损坏：$(tail -2 /tmp/cpio-err.txt)"
fi

say ""
say "⑤ sha256"
sha256sum "$OUTDIR/data-los181.cpio.gz" | tee -a "$LOG"
if [ "$MSZ" = "$DSZ" ]; then adb shell "rm -rf $DEV"; say "   已清理设备侧 $DEV"; fi
say "════════ $(date '+%F %T') 备份结束 ════════"
ls -la "$OUTDIR/data-los181.cpio.gz" | tee -a "$LOG"
