#!/usr/bin/env bash
# 等设备以 Android 身份上线，立刻抓 watchdog / ANR / dropbox 证据
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$DIR/evidence-watchdog-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
echo "[live] 证据目录 $OUT"

echo "[live] 等 Android adbd 上线（最多 10 分钟）..."
ok=0
for i in $(seq 1 120); do
  if adb devices | tail -n +2 | grep -qE "device$"; then ok=1; break; fi
  sleep 5
done
if [ "$ok" -ne 1 ]; then echo "[live] adb 未上线"; exit 2; fi
echo "[live] 设备上线，开始抓取"

adb shell 'getprop ro.boot.mode; getprop sys.boot_completed; getprop ro.lineage.version; getprop init.svc.zygote; getprop init.svc.system_server 2>/dev/null; getprop bpf.progs_loaded; getprop init.svc.netd' > "$OUT/quick.txt" 2>&1
cat "$OUT/quick.txt"

echo "[live] logcat（全缓冲）..."
timeout 180 adb logcat -b all -d > "$OUT/logcat-all.txt" 2>&1 || true
wc -l "$OUT/logcat-all.txt"

echo "[live] 找 watchdog / 卡住的组件 ..."
grep -aiE "WATCHDOG|Blocked in handler|watchdog" "$OUT/logcat-all.txt" | head -25 | tee "$OUT/watchdog-hits.txt"

echo "[live] 抓 dropbox / anr / tombstones ..."
adb shell 'ls -la /data/system/dropbox/ 2>/dev/null | tail -15' > "$OUT/dropbox-list.txt" 2>&1
adb shell 'ls -la /data/anr/ 2>/dev/null; ls -la /data/tombstones/ 2>/dev/null' > "$OUT/anr-list.txt" 2>&1
cat "$OUT/dropbox-list.txt" "$OUT/anr-list.txt"

echo "[live] 拉取最新的 dropbox 条目（watchdog 报告）..."
for f in $(adb shell 'ls -t /data/system/dropbox/ 2>/dev/null | head -4' | tr -d '\r'); do
  adb exec-out cat "/data/system/dropbox/$f" > "$OUT/dropbox-$f" 2>/dev/null && echo "  已取 $f ($(stat -c%s "$OUT/dropbox-$f") 字节)"
done

echo "[live] dmesg ..."
timeout 60 adb shell dmesg > "$OUT/dmesg.txt" 2>&1 || true

echo "[live] 汇总"
printf "  boot_completed = %s\n" "$(adb shell getprop sys.boot_completed | tr -d '\r')"
echo "  证据 -> $OUT"
ls -la "$OUT" | tail -12
