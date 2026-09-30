# SM-G9209 (zerofltectc) —— LineageOS 20 (Android 13) 移植修复

> **⬇️ 下载**：[`zerofltectc-los20-fix-v2.0.zip`](https://github.com/yaxiaiyuting/zerofltectc-los181-fix/releases/latest)（11.6 MB，TWRP 直刷）
>
> 本目录是 v1.0（LOS 18.1 修复）的续作。v1.0 的 README 里曾写明
> *"Android 13 (LOS 20) additionally has an eBPF issue and is not covered"* —— **本文档就是把这个缺口补上**。

> **English TL;DR**: Upgrading the China Telecom Galaxy S6 (SM-G9209 / `zerofltectc`) from
> LineageOS 18.1 to community LineageOS 20 boot-loops forever. Three root causes: (1) the kernel
> lacks the eBPF command `BPF_OBJ_GET_INFO_BY_FD` required by Android 13's `bpfloader`; (2) the
> EUR device tree puts the `s2mpb02` PMIC on the wrong I²C bus (touch never powers up); (3) AOSP's
> `BpfMap.h:53` calls a bare `abort()` when a netd BPF map can't be opened, killing `system_server`
> from the `SyncManager` / `WifiHandlerThread` threads. This release ships a self-compiled kernel
> (eBPF backport + patched DTB) plus three framework fixes, all in one TWRP zip.

---

## 1. 适用范围

| 项目 | 值 |
|---|---|
| 机型 | Samsung Galaxy S6 **SM-G9209**（中国电信版），codename `zerofltectc` |
| 基座 ROM | `lineage-20.0-*-UNOFFICIAL-zeroflte.zip`（Android 13，[fakemanoan 构建](https://fakemanoan.github.io/downloads/s6.html)） |
| Recovery | TWRP 3.7.0_9-2-fakeman |
| 修复包 | `zerofltectc-los20-fix-v2.0.zip`（11.6 MB） |
| 结果 | ✅ 正常开机、触摸可用、eBPF 正常、**应用数据完整保留** ｜ ⚠️ 电信卡无服务 |

---

## 2. 三个根因（全部实机取证）

### ① 内核缺 eBPF 命令 → Android 13 起不来

Android 13 的 `bpfloader` 在加载 BPF 程序后要调用 `BPF_OBJ_GET_INFO_BY_FD`（cmd 15）做去重。
社区内核（`samsungexynos7420/android_kernel_samsung_universal7420` 的 `lineage-20` 分支）
没有实现这个命令，`bpfloader` 失败，`bpf.progs_loaded` 永远不为 1。

**修法**：把 eBPF 回移打进内核并自编译。需要补的东西（见
[`scripts/apply_bpf_backport.py`](scripts/apply_bpf_backport.py)）：

| 文件 | 改动 |
|---|---|
| `include/linux/kernel.h` | 补 `u64_to_user_ptr` |
| `include/uapi/linux/bpf.h` | 补 `BPF_OBJ_GET_INFO_BY_FD` 枚举 + `info` 字段 + 结构体 |
| `init/Kconfig` | 补 `CONFIG_BPF_UNPRIV_DEFAULT_OFF` |
| `kernel/bpf/syscall.c` | 补 4 个函数 + switch case |
| `arch/arm64/configs/exynos7420-zeroflte_defconfig` | 打开相关配置 |

验证：`getprop bpf.progs_loaded` → `1`，且 `kallsyms` 里能看到
`bpf_obj_get_info_by_fd` / `bpf_map_get_info_by_fd` / `bpf_prog_get_info_by_fd`。

内核分支必须是 `lineage-20`（commit `24266d1a3e8c`），**不是** manifest 里的
`lineage-20.0-unify-clang-2`。工具链用 `prebuilts/clang/kernel/linux-x86/clang-r416183b`。

### ② 设备树用错变体 → 触摸永不上电（LOS 18.1 老问题，LOS 20 同样存在）

社区内核在这台机器上装载的是 **EUR** 设备树，`s2mpb02` PMIC 挂在 `hsi2c@14E60000`；
而 CTC 板上它在 **`hsi2c@13670000`**。→ `tsp_avdd` 稳压器注册不出来 → 触摸控制器无供电。

**修法**：把 `s2mpb02@59` 节点从 `hsi2c@14E60000` 移到 `hsi2c@13670000` 后重新打包 DTB。
dtb0 从 186,368 → **184,710** 字节。见 [`scripts/fix_boot.py`](scripts/fix_boot.py)。

> Samsung legacy boot.img 用的是非标准 FDT 变体：子节点 `FDT_BEGIN_NODE` **没有 4 字节长度前缀**，
> 根节点是 `0x00000000` 占位符。常规 dtc/libfdt 解析不了，脚本里是手写的线性解析器。

### ③ `BpfMap.h` 裸 abort() → system_server 无限被杀（最隐蔽的一个）

```cpp
// frameworks/libs/net/common/native/bpf_headers/include/bpf/BpfMap.h:53
BpfMap(const char* pathname, uint32_t flags) {
    mMapFd.reset(mapRetrieve(pathname, flags));
    if (mMapFd < 0) abort();          // ← 裸 abort()，abort 前不打任何日志
    if (isAtLeastKernelVersion(4, 14, 0)) { ... }   // 3.10 内核上是 false，跳过尺寸检查
}
```

3.10 内核上 netd 的 BPF map 打不开 → 直接 `abort()` 整个 `system_server`。

**两个实测触发点**（线程名会告诉你走的是哪条）：

| 触发路径 | 崩溃线程 |
|---|---|
| `SyncManager.getTotalBytesTransferredByUid()` → `TrafficStats.getUidRxBytes/getUidTxBytes` | `SyncManager` / `Thread-10` |
| `WifiMetrics.logStaEvent()` → `TrafficStats.getTotalTxBytes` | `WifiHandlerThre` |

**为什么难查**：
- `libc: Fatal signal 6 (SIGABRT), code -1 (SI_QUEUE)`，但**没有任何中间日志**
- Java try-catch 抓不到（是 C++ abort）
- `Thread.setDefaultUncaughtExceptionHandler` 不触发
- 本内核 **`debuggerd`/`crash_dump` 完全不可用**：
  `crash_dump failed to dump process <pid>: failed to waitpid on child: No child processes`
- `/data/tombstones` 始终为空

**修法**：在 `TrafficStats` 里短路所有走 BPF 的方法（16 处），返回 `UNSUPPORTED`(-1)。
见 [`patches/0001-TrafficStats-shortcircuit-BPF.patch`](patches/0001-TrafficStats-shortcircuit-BPF.patch)。

> 注意：`TrafficStats` 在 Android 13 里属于 **Connectivity 模块**
> （`packages/modules/Connectivity/framework-t/src/android/net/TrafficStats.java`），
> **不在** `frameworks/base`。编出来的 jar 是
> `system/apex/com.android.tethering/javalib/framework-connectivity-t.jar`。

---

## 3. 另外两处必要修复

### ④ netd 缺 CAP_SYS_ADMIN → eBPF map 全部 EPERM

原版 `netd.rc` 的 capabilities 里没有 `SYS_ADMIN`，导致 netd 打开 BPF map 全部
`EPERM`。用「把自己替换成 netd 并记录 syscall 返回值」的探针法实机证明：

| netd.rc | `BPF_OBJ_GET` 结果 |
|---|---|
| 原版 | `-1 (EPERM)` |
| 加 `SYS_ADMIN` | `3` / `4` / `5`（成功） |

修法：`/system/etc/init/netd.rc` 的 capabilities 加 `SYS_ADMIN`。

> ⚠️ 只加 `SYS_ADMIN`，**不要**加 `BPF` —— 加了反而会让 EPERM 复现。

### ⑤ gpuservice 在 3.10 内核上崩

`7420_patches` 里的修法：`/system/etc/init/gpuservice.rc` 加一行 `disabled`。

---

## 4. 安装

```
1) 先刷 lineage-20.0-*-UNOFFICIAL-zeroflte.zip
2) （可选）刷 MindTheGapps 13.0 arm64
3) TWRP → Install → zerofltectc-los20-fix-v2.0.zip
4) Reboot System（先拔 USB，避免进充电模式）
```

脚本会校验机型，并把原 boot 备份到 `/sdcard/boot-backup-before-los20-fix.img`。

### ⚠️ 关于「保留数据」

本包**不需要**清数据。从 LOS 18.1 dirty flash 上来时：

- `/data` 在本机型上**未加密**（`ro.crypto.state=unencrypted`），且已经是 FUSE 布局
  （`persist.sys.fuse=true`），与 Android 13 兼容 → **直接刷即可，不用 format**
- `/data/swapfile`（8 GB Magisk swap 文件）建议先删掉再备份，省一半空间

**升级前务必备份 `/data`**。注意 `adb exec-out` 会**静默截断 >200 MB 的流**
（实测 28 GB 只出来 233 MB，且设备侧返回码还是 0）。
正确做法是**设备端分块 + `adb pull`**，见 [`scripts/backup-data-pull.sh`](scripts/backup-data-pull.sh)。

### 升级后可能遇到的两个坑

| 现象 | 原因 | 修法 |
|---|---|---|
| 输原密码解不开锁屏 | 跨版本后 gatekeeper 凭据对不上 | 删 `/data/system/locksettings.db*` + 清空 `/data/misc/gatekeeper/`（应用数据不受影响） |
| 卡在开机（system_server 死等 thermal HAL） | `/vendor/bin/hw/android.hardware.thermal@2.0-service.samsung` 被截断成 1 字节 | 从 ROM 镜像恢复该文件（149,264 字节），SELinux 标签设为 `u:object_r:hal_thermal_default_exec:s0` |

> TWRP 下路径坑：`/system` 是挂载点，**真实根是 `/system/system/...`**。
> 运行中的系统里则是 `/system/apex/...`（`/vendor` 是 `/system/vendor` 的符号链接）。

---

## 5. root：用 KernelSU，不要用 Magisk

### 内核本来就内置 KernelSU

自编译内核里 `CONFIG_KSU=y`（源码在 `drivers/kernelsu/`，`KSU_VERSION=12126`），
**根本不需要 Magisk**。

### Magisk 为什么走不通（3 次尝试全失败）

| 尝试 | 结果 |
|---|---|
| TWRP 直刷 `Magisk-v30.7.apk` | `magiskboot dtb extra test` 失败 → `boot_patch.sh` abort |
| 设备端手工 patch ramdisk + 宿主机重打包 | 结构验证全绿（kernel/DTB 逐字节相同、只换 ramdisk），**卡第一屏无红字** |
| 从干净基线精确重打包 | 同上 |

**根因**：`magiskboot` 处理不了三星的 **DHTB** 设备树封装（`extra` 不是裸 FDT，
而是 DHTB 表 + 多个 DTB 条目）。即使绕过这步、结构完全正确，
Magisk 的 `magiskinit` 替换链在本机的 `skip_initramfs` 引导流程下也走不通。

### KernelSU 正确用法

**Manager 版本必须匹配内核**。内核 `KSU_VERSION=12126`，装最新版会报红字：

> 当前 KernelSU 版本 12126 过低，管理器无法正常工作，请将内核 KernelSU 版本升级至 **32377** 或以上！

各发布版的 versionCode：

| 发布版 | versionCode |
|---|---|
| v1.0.3 | 12018 |
| **v1.0.5** | **12081** ← 内核 12126 最接近的发布版 |
| v2.0.0 | 22001 |
| v3.0.0 | 32179 |
| v3.2.4 | 32457 |

⇒ **用 v1.0.5**：

```bash
curl -L -O https://github.com/tiann/KernelSU/releases/download/v1.0.5/KernelSU_v1.0.5_12081-release.apk
adb install -r -d KernelSU_v1.0.5_12081-release.apk
adb shell monkey -p me.weishu.kernelsu -c android.intent.category.LAUNCHER 1
```

### 内核只认这些签名

`drivers/kernelsu/apk_sign.c` 的白名单（另外 **APK 必须只有 v2 签名**，有 v3/v3.1 会被拒）：

```c
0x363 "4359c171..."  // dummy.keystore
0x33b "c371061b19d8c7d7d6133c6a9bafe198fa944e50c1b31c9d8daa8d7f1fc2d2d6"  // ksu official
384   "7e0c6d72..."  // 5ec1cff/KernelSU
0x375 "484fcba6..."  // KOWX712/KernelSU
0x396 "f415f4ed..."  // rsuntk/KernelSU
0x3e6 "79e59011..."  // rifsxd/KernelSU-Next
0x35c "947ae944..."  // ShirkNeko/SukiSU-Ultra
```

### 验证 root 生效

`/data/adb/` 权限是 `drwx------ root root`（普通应用读不了），
但 KernelSU Manager 能列出模块数和超级用户列表 ⇒ **Manager 确实拿到了 root**。

设备上的关键路径：

| 路径 | 说明 |
|---|---|
| `/data/adb/ksu/.allowlist` | 已授权列表（**按包名存储**，format v3） |
| `/data/adb/ksu/bin/` | `ksud` `busybox` `resetprop` `magiskboot` `bootctl` |
| `/data/adb/modules/` | 模块目录 |
| `/system/bin/su` | **内核伪造的**（`ls` 看得到、读不到内容）—— 正常现象 |

---

## 6. 开机后验证

```bash
adb shell getprop sys.boot_completed                      # 1
adb shell getprop bpf.progs_loaded                        # 1
adb shell grep -c sec_touchscreen /proc/bus/input/devices # 2
adb shell getprop init.svc.vendor.touch-hal-1-0-samsung   # running
adb shell getprop init.svc.vendor.thermal-hal-2-0         # running
adb shell getprop init.svc.netd                           # running
adb shell dumpsys package me.weishu.kernelsu | grep versionName   # v1.0.5（若装了 KernelSU）
```

---

## 7. 已知限制

- **蜂窝网络不可用**：Qualcomm MDM9635M modem 不被社区内核支持，无 VoLTE。当 WiFi 设备用。
- 第一屏 `KERNEL IS NOT STANDARD ENFORCING` 是三星对第三方内核的正常警告，不影响启动。
- 刷完本包会覆盖 boot 分区，KernelSU 需按 §5 重装 Manager。

---

## 8. 目录说明

```
los20/
├── README.md                                  ← 本文件
├── docs/
│   ├── LOS20-开机阻塞点-工作日志.md            ← 完整排查过程（6 个阻塞点逐一击破）
│   ├── KernelSU-root-方案.md                  ← root 方案详解
│   ├── LOS20升级-可行性与实施方案.md           ← 升级前的可行性调研
│   └── 社区版本与自编译可行性.md
├── scripts/
│   ├── apply_bpf_backport.py                  ← eBPF 回移补丁（5 处改动）
│   ├── fix_boot.py                            ← DTB 触摸修复（手写三星 FDT 解析器）
│   ├── repack_boot_magisk.py                  ← 三星 DHTB 格式 boot 重打包（含自检）
│   ├── swap_dtb.py                            ← DTB 替换工具
│   ├── backup-data-pull.sh                    ← /data 全量备份（绕开 adb exec-out 截断）
│   ├── bpfget.c / bpfget2.c / maptest.c       ← 裸机 aarch64 BPF 探针（诊断用）
│   └── crashgrab.c                            ← ptrace 崩溃抓取器（未完成，留档）
└── patches/
    ├── 0001-TrafficStats-shortcircuit-BPF.patch              ← 修 SyncManager/WiFi 崩溃
    ├── 0002-FrameworkFacade-shortcircuit-TrafficStats.patch  ← WiFi 侧同样短路
    └── 0003-ClientModeImpl-guards-INEFFECTIVE.patch          ← 无效尝试，仅留档
```

---

## 9. 给维护者的上游修复建议

1. **内核**：把 eBPF 回移（含 `BPF_OBJ_GET_INFO_BY_FD`）合进
   `lineage-20` 分支。参考实现是
   [`lineage-21.0-bpf-alpha`](https://github.com/samsungexynos7420/android_kernel_samsung_universal7420)
   分支（commit `e487cc3a607`）。
2. **设备树**：把仓库里已有的 `exynos7420-zeroflte_chn_*.dtb` 也编进 DTB 表
   （社区源码里 CHN 变体是对的，只是没被编进去）。
3. **`BpfMap.h`**：`if (mMapFd < 0) abort();` 建议改成打日志返回错误。
   AOSP 自己的注释也承认这里该返回错误，但在 eBPF 不完整的移植内核上代价太大。
4. **`netd.rc`**：在 3.10 这类 eBPF 回移内核上补 `SYS_ADMIN`。

---

## 10. 致谢

- 社区 ROM 与内核：[fakemanoan](https://fakemanoan.github.io/downloads/s6.html) /
  [samsungexynos7420](https://github.com/samsungexynos7420)
  （`7420_patches`、`local_manifests`、`android_kernel_samsung_universal7420`）
- [KernelSU](https://github.com/tiann/KernelSU) —— 本机 root 方案
- 本仓库的取证、定位与打包由 SM-G9209 实机完成（2026-09-29 ~ 2026-10-01）
