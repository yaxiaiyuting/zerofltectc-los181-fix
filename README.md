# SM-G9209 (Galaxy S6 中国电信版 / zerofltectc) —— LineageOS 移植修复

> ## 🆕 v2.0 已发布：LineageOS **20** (Android 13) 修复
>
> 从 LOS 18.1 升到 LOS 20 会无限卡开机 —— 三个根因（内核缺 eBPF 命令、
> 设备树用错变体、AOSP `BpfMap.h` 裸 `abort()` 杀 system_server）已全部解决。
> 修复包：**[`zerofltectc-los20-fix-v2.0.zip`](https://github.com/yaxiaiyuting/zerofltectc-los181-fix/releases/latest)**（11.6 MB，TWRP 直刷）
> ｜ 详情：**[`los20/README.md`](los20/README.md)**
>
> root 用 **KernelSU**（内核已内置 `CONFIG_KSU=y`），不要用 Magisk。

---

# （v1.0）LineageOS 18.1 移植修复

> **⬇️ 下载修复包**：[`zerofltectc-los181-fix-v1.0.zip`](https://github.com/yaxiaiyuting/zerofltectc-los181-fix/releases/latest)（8.3 MB，TWRP 直刷）
>
> **📄 给维护者的 bug 报告**：[`upstream/ISSUE.md`](upstream/ISSUE.md) ｜ **📋 发布指南**：[`PUBLISHING.md`](PUBLISHING.md)

> **一句话**：社区 LineageOS 18.1 刷进 SM-G9209 后会永远卡在开机动画、触摸屏全程失灵。
> 本仓库给出一份 **8 MB 的 TWRP 修复包**，刷完即可正常进系统并使用触摸屏。
>
> **English TL;DR**: Community LineageOS 18.1 (zeroflte) boot-loops forever on the China Telecom
> variant SM-G9209 (`zerofltectc`), and the touchscreen never works. Root cause: the kernel ships the
> **EUR** device tree on this board, where the `s2mpb02` PMIC sits on the wrong I²C bus — so the
> `tsp_avdd` regulator never registers, the touch controller is never powered, the touch HAL never
> registers `IStylusMode`, and `system_server`'s main thread blocks in `HwBinder.getService()` until
> the watchdog kills it. Flash the fix zip after the official ROM; see [Install](#安装).

---

## 1. 适用范围

| 项目 | 值 |
|---|---|
| 机型 | Samsung Galaxy S6 **SM-G9209**（中国电信版），codename `zerofltectc`，bootloader `G9209KEU2ERI2` |
| 基座 ROM | `lineage-18.1-*-UNOFFICIAL-zeroflte.zip`（Android 11，[fakemanoan 构建](https://fakemanoan.github.io/downloads/s6.html)） |
| Recovery | TWRP 3.7.0_9-2-fakeman（或更高） |
| 修复包 | `zerofltectc-los181-fix-v1.0.zip`（8.3 MB） |
| **v2.0（LOS 20）** | **[`zerofltectc-los20-fix-v2.0.zip`](https://github.com/yaxiaiyuting/zerofltectc-los181-fix/releases/latest)**（11.6 MB，Android 13）→ [`los20/README.md`](los20/README.md) |
| 结果 | ✅ 正常开机、触摸可用、Wi-Fi/传感器/音频/存储正常 ｜ ⚠️ 电信卡无服务（见 §7） |

> 本修复包**只适用于 SM-G9209**（安装脚本会校验机型，其他机型会被拒绝）。G920F 等欧版机型
> 的触摸供电本来就在另一条总线上，强行刷入会导致触摸失效。

---

## 2. 症状

刷入社区 LOS 18.1 / LOS 20 后：

* 能亮屏，能看到 LineageOS 开机动画，**但永远进不去系统**
* Android 11：约每 100 秒框架重启一次（`system_server` 被 watchdog 杀掉）
* Android 13：`init` 直接卡在 `bpfloader`，USB 都不枚举，adb 完全不上线
* **触摸屏全程失灵**（连 TWRP 里也只能用音量键 + 电源键操作）
* 第一屏的 `KERNEL IS NOT STANDARD ENFORCING` 是三星 bootloader 对第三方内核的常规提示，**不是故障**

---

## 3. 根因

三层因果，每一层都有实机证据：

### ① 设备树用错变体 → 触摸控制器没有供电

社区内核在这台机器上装载的是 **EUR（欧版）** 设备树：

```
/proc/device-tree/model = "Samsung ZERO-F LTE EUR rev06 board based on Exynos7420(EVT1), mPOP"
```

而原厂 BOOT 分区里的 5 个 DTB 全部是 **`ZERO-F LTE CHN`**（rev04/05/06a/06/07）。
差别在触摸供电轨：

| 定义 | CHN（CTC 正确） | EUR（社区） |
|---|---|---|
| `s2mpb02@59`（提供 `tsp_avdd` = LDO17） | 挂在 **`hsi2c@13670000`** | 挂在 **`hsi2c@14E60000`** ❌ |

于是：

```
s2mpb02_i2c_probe: device not found on this channel!!          ← PMIC 探测失败
fts_touch 7-0049: fts_power_ctrl: Failed to get tsp_avdd regulator.
fts_touch 7-0049: fts_read_chip_id failed. ret: -121           ← 触摸芯片无响应
fts_touch: probe of 7-0049 failed with error 1                 ← 触摸屏驱动没起来
```

输入设备列表里因此只有 `sec_touchkey`（电容键），**没有触摸屏**。

### ② 触摸 HAL 不注册接口（且 ROM 还漏装了它的 init rc）

`vendor.lineage.touch@1.0-service.samsung` 二进制、SELinux 域、hwservice 标签在 ROM 里都存在，
但 **没有任何 rc 文件启动这个服务**（ROM 打包遗漏）：

```
init: Could not find 'vendor.lineage.touch@1.0::IStylusMode/default' for ctl.interface_start
```

### ③ 框架同步阻塞查询该接口 → watchdog 杀 system_server → 无限重启

`/data/system/dropbox/system_server_watchdog@*.txt.gz` 里的主线程堆栈：

```
"main" prio=5 tid=1 Native
  at android.os.HwBinder.getService(Native method)
  at vendor.lineage.touch.V1_0.IStylusMode.getService(IStylusMode.java:55)
  at lineageos.hardware.LineageHardwareManager.getHIDLService(LineageHardwareManager.java:308)
  at lineageos.hardware.LineageHardwareManager.isSupported(LineageHardwareManager.java:258)
  at com.android.server.inputmethod.InputMethodManagerService.updateTouchHovering(InputMethodManagerService.java:3113)
  at com.android.server.inputmethod.InputMethodManagerService.systemRunning(InputMethodManagerService.java:1888)
  at com.android.server.SystemServiceManager.startBootPhase(SystemServiceManager.java:208)
  at com.android.server.SystemServer.startOtherServices(SystemServer.java:2265)
```

主线程死等 60 秒 → watchdog 杀掉 `system_server` → `zygote` 重启 → **无限开机动画**。

---

## 4. 修复内容

修复包做两件事，**缺一不可**：

| # | 修复 | 实现方式 |
|---|---|---|
| ① | 设备树：把 `s2mpb02@59` 搬回 `hsi2c@13670000` | 替换 boot 镜像（内核不变，仅 DTB 表；**同 DTB 内节点搬移，phandle 不受影响**） |
| ② | 触摸 HAL 的 init rc | 写入 `/vendor/etc/init/vendor.lineage.touch@1.0-service.samsung.rc` |

安装脚本会自动：校验机型 → 备份原 boot 到 `/sdcard/boot-backup-before-fix.img` → 写 BOOT → 写 rc（自动适配 SAR / 非 SAR 布局）。

---

## 5. 安装

```
1) 先刷官方 lineage-18.1-*-UNOFFICIAL-zeroflte.zip（若尚未刷）
2) TWRP → Install → zerofltectc-los181-fix-v1.0.zip → 滑动刷入
3) Reboot → System（拔掉 USB 线再开机，避免进入充电模式）
4) 首次开机约 1-3 分钟
```

> ⚠️ 若你之前用 Magisk / KernelSU 打过 boot，本包会覆盖它，开机后需重新刷一次 root。

## 6. 验证

```bash
adb shell 'grep -E "Name=\"sec_touchscreen\"" /proc/bus/input/devices'
# N: Name="sec_touchscreen"   Handlers=event1 dt2w_input      ← 触摸屏出现

adb shell getprop init.svc.vendor.touch-hal-1-0    # running
adb shell getprop sys.boot_completed               # 1
adb shell 'ls /data/system/dropbox | wc -l'        # 不再新增 watchdog 报告
```

实机验收结果（2026-09-29，SM-G9209）：

| 检查项 | 修复前 | 修复后 |
|---|---|---|
| 触摸屏输入设备 | 只有 `sec_touchkey` | ✅ **`sec_touchscreen`** |
| 触摸 HAL | 未启动 | ✅ `vendor.touch-hal-1-0 = running` |
| `sys.boot_completed` | 永远 0 | ✅ **1** |
| FATAL / WATCHDOG | 每 ~100 秒一次 | ✅ **0** |
| 系统 | — | ✅ LineageOS 18.1 (Android 11)，持续运行 30 分钟以上 |

---

## 7. 已知限制

* **蜂窝网络不可用**：本机是**高通 MDM9635M 基带**（`persist.ril.modem.board=MDM9635M`）+ 双卡 CDMA，
  社区树只支持三星 Shannon 基带机型，RIL/QMI 栈缺失 → `OUT_OF_SERVICE`、无通话无短信。
  本机在 LineageOS 下适合当 **Wi-Fi 终端**；需要语音请留在原厂 Android 7。
* **VoLTE 永久无解**：三星私有 IMS 栈，LineageOS 上从来不可用。
* **Android 13 (LOS 20) 另有 eBPF 兼容问题**：`bpfloader` 加载 tethering BPF 程序时挂死；
  关掉 BPF JIT 后可加载，但 `netd_shared/netd.o` 建 map 返回 EPERM（内核 `bpf_obj_get_info_by_fd`
  未实现导致重复加载、memlock 记账爆掉），随后 `reboot_on_failure` 主动重启。
  → **本机现实目标是 Android 11**。
* 相机 OIS 伴生芯片、部分三星私有功能（如虹膜/心率）不可用。

---

## 8. 给上游维护者的正确修法

本次修复是**二进制层面的定点修复**。源码层面的正确修法更简单 ——
**社区内核源码里 CHN 变体本来就是对的**：

```dts
/* arch/arm64/boot/dts/exynos7420-zeroflte_chn_00.dts（源码已存在且正确） */
hsi2c@13670000 {
    ...
    s2mpb02@59 {          /* ← tsp_avdd = s2mpb02-ldo17，位置正确 */
```

问题在于 **DTB 打包时只包含了 EUR 变体**：

```make
# arch/arm64/boot/dts/Makefile
dtb-$(CONFIG_BOARD_ZEROFLTE) += exynos7420-zeroflte_eur_open_00.dtb \
                                ... \
                                exynos7420-zeroflte_eur_open_07.dtb      # ← 没有 chn / ctc
```

因此 SM-G9209（`hw_rev=10` → 需要 CHN rev06）只能落到 EUR 设备树上。

**建议的两处上游改动**：

1. 在 `arch/arm64/boot/dts/Makefile` 中为 `CONFIG_BOARD_ZEROFLTE` 追加
   `exynos7420-zeroflte_chn_00..06.dtb`，并让 DTB 表为这些条目写上对应的 `hw_rev`
   （原厂表：rev04→7、rev05→8、rev06a→9、rev06→10、rev07→0）。
2. 触摸 HAL 的 init rc 未被安装：`vendor.lineage.touch@1.0-service.samsung.rc`
   应在构建时随 HAL 一起装入 `/vendor/etc/init/`（本 ROM 的其他 lineage HAL 如
   `livedisplay` / `fastcharge` / `trust` 都有 rc，只有 touch 缺）。

---

## 9. 复现与取证方法

本次定位全程可复现（脚本见本仓库 `scripts/`）：

| 目的 | 方法 |
|---|---|
| 拿上次启动的内核日志（TWRP 内） | `adb exec-out cat /proc/last_kmsg` |
| 拿框架卡点堆栈 | `adb shell ls -t /data/system/dropbox/` → `system_server_watchdog@*.txt.gz` |
| 看设备树实际用哪个变体 | `cat /proc/device-tree/model` |
| 看触摸驱动是否起来 | `dmesg | grep fts_touch`（TWRP 或 root 下） |
| 解析/移植 DTB | `dtc -I dtb -O dts` / `dtc -I dts -O dtb`，用 `libfdt` 或文本搬移节点 |

---

## 10. 免责声明

刷机有风险。本修复包经 SM-G9209 实机验证，但**不对任何数据丢失或设备损坏负责**。
刷前请务必备份 EFS / 基带分区（`EFS`、`m9kefs1-3`、`RADIO`、`PARAM`、`PERSISTENT`）与原厂四件套固件。

## 11. 致谢

* [samsungexynos7420](https://github.com/samsungexynos7420) —— 设备树与内核源码
* [fakemanoan](https://fakemanoan.github.io/downloads/s6.html) —— LineageOS 构建
* 定位过程使用的工具链：`dtc` / `libfdt` / `sdat2img` 流程
