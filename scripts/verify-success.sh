#!/usr/bin/env bash
# 等设备上线后做完整验收（Android 11 / LineageOS 18.1 on SM-G9209 CTC）
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$DIR/verify-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
echo "验收目录: $OUT"
echo "等待设备上线（最多 15 分钟，插上 USB 即可）..."
ok=0
for i in $(seq 1 180); do
  if adb devices | tail -n +2 | grep -qE "device$"; then ok=1; break; fi
  sleep 5
done
[ "$ok" -ne 1 ] && { echo "设备未上线"; exit 1; }
MODE=$(adb shell getprop ro.boot.mode 2>/dev/null | tr -d '\r')
echo "设备已上线 (ro.boot.mode='${MODE:-正常启动}')"
sleep 5

echo; echo "════════ 1) 基本状态 ════════"
adb shell 'for p in ro.lineage.version ro.build.version.release ro.build.version.security_patch \
  sys.boot_completed ro.boot.mode ro.boot.bootloader ro.product.device \
  bpf.progs_loaded init.svc.netd init.svc.zygote init.svc.vold init.svc.ril-daemon init.svc.ksud; do
  printf "%-38s %s\n" "$p" "$(getprop $p)"; done' | tee "$OUT/01-props.txt"

echo; echo "════════ 2) 触摸屏（本次修复的核心）════════"
adb shell 'dmesg 2>/dev/null | grep -iE "fts_touch|tsp_avdd" | tail -10' | tee "$OUT/02-touch-dmesg.txt"
adb shell 'grep -E "^N: Name|^H: Handlers" /proc/bus/input/devices | head -14' | tee "$OUT/02-input-devices.txt"
adb shell 'getprop | grep -iE "touch|tsp" | head -8' | tee -a "$OUT/02-input-devices.txt"

echo; echo "════════ 3) 硬件功能 ════════"
{
echo "--- Wi-Fi ---"; adb shell 'dumpsys wifi 2>/dev/null | grep -m3 -iE "Wi-Fi is|mNetworkInfo|SSID"'
echo "--- 相机 ---"; adb shell 'dumpsys media.camera 2>/dev/null | grep -m6 -iE "Camera [0-9]|Number of camera|Device.*status"'
echo "--- 传感器 ---"; adb shell 'dumpsys sensorservice 2>/dev/null | head -12'
echo "--- 音频 ---"; adb shell 'dumpsys audio 2>/dev/null | grep -m5 -iE "Devices|mode|Stream"'
echo "--- 电池/温度 ---"; adb shell 'dumpsys battery 2>/dev/null | head -10'
echo "--- 存储 ---"; adb shell 'df -h /data /system 2>/dev/null'
echo "--- CPU/内存 ---"; adb shell 'cat /proc/loadavg; free -m 2>/dev/null | head -3'
} | tee "$OUT/03-hardware.txt"

echo; echo "════════ 4) 蜂窝/电信卡（预期不可用）════════"
{
adb shell 'getprop | grep -iE "gsm\.|ril\.|persist.radio" | head -12'
adb shell 'dumpsys telephony.registry 2>/dev/null | grep -m6 -iE "mServiceState|mSignalStrength|mCallState"'
} | tee "$OUT/04-telephony.txt"

echo; echo "════════ 5) 日志与崩溃检查 ════════"
timeout 90 adb logcat -b all -d > "$OUT/05-logcat.txt" 2>&1
echo "logcat: $(wc -l < "$OUT/05-logcat.txt") 行"
grep -acE "FATAL EXCEPTION|WATCHDOG|system_server.*died" "$OUT/05-logcat.txt" | xargs echo "严重错误计数:"
adb shell 'ls -la /data/system/dropbox/ 2>/dev/null | tail -5' | tee "$OUT/05-dropbox.txt"
adb shell 'cat /proc/uptime' | tee -a "$OUT/05-dropbox.txt"

echo; echo "════════ 验收完成 ════════"
echo "结果目录: $OUT"
