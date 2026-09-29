#!/usr/bin/env bash
# TWRP 侧取证：抓上一次「卡在开机动画」那次的完整证据
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$DIR/evidence-stuck-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
echo "证据目录: $OUT"

echo "### 1) 上一次启动的内核日志（卡点就在这个尾巴里）"
timeout 180 adb exec-out cat /proc/last_kmsg > "$OUT/last_kmsg.log" 2>/dev/null
if [ -s "$OUT/last_kmsg.log" ]; then
  echo "大小: $(stat -c%s "$OUT/last_kmsg.log") 字节 / $(wc -l < "$OUT/last_kmsg.log") 行"
  echo "--- 属于哪次启动 ---"
  grep -a -m1 "androidboot.mode" "$OUT/last_kmsg.log" | cut -c1-160
  echo
  echo "--- 关键标记 ---"
  for pat in "Userdata mounted using" "Failed to mount" "e2fsck" "mount_all" "nonencrypted" \
             "init: Starting service 'zygote'" "init: Starting service 'vold'" "vold" "vdc" \
             "post-fs-data" "late-fs" "bootanim" "checkpoint" "metadata"; do
    printf "  %-34s %s 次\n" "$pat" "$(grep -ac "$pat" "$OUT/last_kmsg.log" 2>/dev/null || echo 0)"
  done
  echo
  echo "--- 最后 45 行（卡住的瞬间）---"
  tail -45 "$OUT/last_kmsg.log"
else
  echo "last_kmsg 为空"
fi

echo
echo "### 2) ROM 的 init.rc / fstab（判断卡在哪一段）"
adb shell '
mount -t ext4 -o ro /dev/block/by-name/SYSTEM /system 2>/dev/null
echo "--- /system/system/etc/init/hw/init.rc 的 post-fs-data 段 ---"
awk "/^on post-fs-data/,/^on [a-z-]+$/" /system/system/etc/init/hw/init.rc 2>/dev/null | head -40
echo
echo "--- 是否存在 /metadata 相关配置 ---"
grep -rn "metadata" /system/system/etc/init/hw/*.rc 2>/dev/null | head -10
' | tee "$OUT/init-analysis.txt"

echo
echo "### 3) /data 是否被 ROM 动过（判断它有没有走到 post-fs-data）"
adb shell '
mount -t ext4 -o ro /dev/block/by-name/USERDATA /data 2>/dev/null
echo "顶层内容:"; ls -a /data | head -20
echo "条目数: $(ls -a /data | wc -l)   （只有 lost+found/media ≈ ROM 从未挂载过 /data）"
echo "--- /cache ---"; mount -t ext4 -o ro /dev/block/by-name/CACHE /cache 2>/dev/null; ls -a /cache | head -10
' | tee "$OUT/data-state.txt"

echo
echo "### 4) 恢复 TWRP 的 ORS 状态（确认没有残留脚本会干扰下次启动）"
adb shell 'ls -la /cache/recovery/ 2>/dev/null | head -8; cat /cache/recovery/command 2>/dev/null'
echo
echo "取证完成 -> $OUT"
