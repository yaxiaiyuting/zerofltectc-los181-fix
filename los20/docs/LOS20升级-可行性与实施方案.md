# SM-G9209 保留数据升级 LineageOS 20（Android 13）—— 可行性调研与实施记录

调研时间：2026-09-30
设备：Samsung SM-G9209（`zerofltectc`，CTC 板）/ Exynos 7420 / 高通 MDM9635M 基带
当前系统：**LineageOS 18.1**（`18.1-20260415-UNOFFICIAL-zeroflte`，内核 `3.10.108-03753-g745d337c7142`）
目标：保留数据（至少保留应用）升级到 LineageOS 20（`lineage-20.0-20260409-UNOFFICIAL-zeroflte.zip`）

参照文档：
- [修复报告.md](修复报告.md)（触摸修复的报告）
- [主线内核vs自编译高版本ROM-调研与推荐.md](主线内核vs自编译高版本ROM-调研与推荐.md)（§8.2 已定位 eBPF 坎）
- [release-notes.md](../release-notes.md)（v1.0 发布说明）

---

## 〇、结论速览

| 问题 | 结论 | 证据强度 |
|---|---|---|
| **触摸修复能否移植到 LOS 20？** | ✅ **能，且已验证** —— LOS 20 的 boot.img 里 DTB 表与 18.1 **逐字节相同**，同样的节点搬移补丁适用 | 一手实测（字节级比对 + 重编译自检） |
| **`/system` 装得下 LOS 20 吗？** | ✅ 装得下。LOS 20 system 镜像 1.92 GB，分区 3.19 GB，余量约 1.27 GB | 一手实测 |
| **能保留 /data（应用与数据）吗？** | ✅ 能。当前 /data **未加密**，且已是 FUSE 存储布局（`persist.sys.fuse=true`、`/data/media/0/Android`），与 Android 13 要求一致，**dirty flash 不需要 format data** | 一手实测 |
| **LOS 20 现在能开机吗？** | ❌ **不能 —— 卡在 eBPF，且根因已在源码级钉死**：这版 LOS 20 的 ROM 内核取自内核仓库 `lineage-20` 分支，该分支**没有** `bpf_obj_get_info_by_fd` 这个 syscall（Android 13 的 bpfloader 靠它做程序去重），而 `bpfloader.rc` 里写死 `reboot_on_failure reboot,bpfloader-failed` → **必然开机重启循环** | 源码级（git）+ system 镜像实测 + 与 §8.2 现场日志吻合 |
| **有救吗？** | ⚠️ 有，但要动 ROM（两条路，见 §5）。**不改东西直接刷，一定起不来。** | 推断 |

**一句话**：**保留数据这件事完全可行，触摸修复也已经做好；唯一挡路的是 eBPF，而它是这版 ROM 的固有缺陷，必须先在 ROM 侧处理掉。**

---

## 一、设备现状实测（升级前基线）

```
ro.lineage.version         18.1-20260415-UNOFFICIAL-zeroflte
ro.build.version.release   11   (SDK 30)
内核                        3.10.108-03753-g745d337c7142   # 与 ROM 包内 boot.img 完全一致（未被 Magisk 改）
sys.boot_completed         1
ro.crypto.state            unencrypted          ← 关键：/data 未加密
persist.sys.fuse           true                 ← 关键：已是 FUSE 存储
/dev/block/by-name/        无 HIDDEN 分区（CTC 特有：DNT/SBFS/STEADY/PERSDATA/TOMBSTONES）
已装应用                    234 个（含 17 个 com.google.*，MindTheGapps 11 + Magisk 31.0）
/data 占用                  12 GB / 26 GB
```

分区容量：

| 分区 | 字节 | 说明 |
|---|---|---|
| SYSTEM (`sda18`) | 3,187,671,040 (3.19 GB) | LOS 20 镜像 1.92 GB → 够 |
| USERDATA (`sda20`) | 28,349,300,736 (28.35 GB) | 保留不动 |
| CACHE (`sda19`) | 209,715,200 (200 MB) | |
| RECOVERY (`sda9`) | 35,651,584 | **当前是原厂 recovery，不是 TWRP** |

⚠️ **重要发现**：`/dev/block/by-name/RECOVERY` 的 md5 与 `twrp-backup-20260929/RECOVERY.img`（刷机前备份的原厂镜像）**完全一致** —— 说明**设备上现在没有 TWRP**。要刷 LOS 20 必须先装回 TWRP（可从已 root 的系统直接 `dd` 写 recovery 分区，见 §6）。

---

## 二、触摸修复的可移植性（已解决）

### 2.1 boot.img 结构对比

| 项 | LOS 18.1 | LOS 20 |
|---|---|---|
| kernel | 21,309,296 B（`3.10.108-03753-g745d337c7142`，GCC 4.9） | 23,326,120 B（`3.10.108-124029-g24266d1a3e8c`，Clang 12） |
| ramdisk | 625,048 B | 1,022,432 B |
| DTB 表（DHTB v2，2 条目） | 374,800 B | 374,800 B |

**两个 ROM 的 DTB 段逐字节相同**（`cmp` 无差异），包括：
- `dtb0`（hw_rev=7420，`model_info-hw_rev=10..11` → 本机 `androidboot.hw_rev=10` 选中它）
  → `Samsung ZERO-F LTE EUR rev06 ...`，`s2mpb02@59` 挂在 **`hsi2c@14E60000`**（EUR 布线）
- `dtb1`（hw_rev=0）→ `... EUR rev09 ...`

而原厂 CHN rev06 DTB（`twrp-backup-20260929/dtb/stock_dtb_3.dtb`）里 `s2mpb02@59` 挂在 **`hsi2c@13670000`**。两者节点内容**只差 2 个字面量**：

```
s2mpb02,irq-gpio = <0x67 0x02 0x00>;   (CHN 原厂)
s2mpb02,irq-gpio = <0x56 0x02 0x00>;   (社区 EUR)
pinctrl-0 = <0x68>;                     (CHN 原厂)
pinctrl-0 = <0x57>;                     (社区 EUR)
```

⇒ **修法就是把节点搬到 CHN 总线**（和 18.1 用的修法完全相同）。

### 2.2 补丁工具与自检

工具：`los20-work/fix_boot.py`（线性、无依赖，只用到 `dtc`）

流程：解包 boot.img → 取 DHTB 表条目 0 → `dtc` 反编译 → 把 `s2mpb02@59`
从 `hsi2c@14E60000` 搬到 `hsi2c@13670000` → `dtc` 重编译 → 回填 DHTB 表
（更新 size，保持 offset 与对齐）→ 重新打包 → **回读自检**。

**回归验证**：拿 LOS 18.1 的**原始** boot.img 跑一遍，结果与设备上**实机在用的**修复镜像几乎一致：

| | 我的重编译 | 实机在用（`boot-los181-touchfix.img`） |
|---|---|---|
| dtb0 大小 | 184,710 B | 184,712 B（多 2 字节尾部填充） |
| 节点落位 | `s2mpb02@59` 父节点 = `hsi2c@13670000` | 同 |
| DTS 结构与 ROM 原版差异块数 | 2（纯删除+插入，无其它改动） | 同 |

**LOS 20 产物已生成**：`los20-work/boot-20.0-touchfix.img`（24,727,552 B，md5 `27922eab...`）

---

## 三、空间与数据账（都不挡路）

- LOS 20 system 镜像 = 468,310 块 × 4096 = **1.92 GB**；分区 3.19 GB → 余 1.27 GB。
  TWRP 装完会自动 `resize2fs` 把文件系统扩到填满分区（updater-script 里就有这一步）。
- `/data` 28.35 GB、已用 12 GB。当前**未加密**，ROM 的 fstab 里也没有 `forceencrypt`。
- **存储布局已经兼容 Android 13**：`persist.sys.fuse=true`、`/data/media/0/` 下已有
  `Android/` 目录、`/storage/emulated` 已经是 `/dev/fuse`。
  ⇒ **dirty flash（不 format data）在存储这一层没有障碍。**
- 副作用：`/system` 被 `block_image_update` 全量覆盖 → **GApps 会没**，需要重刷 Android 13 版
  MindTheGapps；`boot` 被覆盖 → **Magisk 会没**（可用 Magisk 应用重新 patch boot，或改用
  ROM 自带/自编译 KernelSU）。

---

## 四、真正的拦路虎：eBPF（源码级钉死）

### 4.1 这版 LOS 20 的内核是哪个分支

ROM 内核版本串：`3.10.108-124029-g24266d1a3e8c`。

在内核仓库 `samsungexynos7420/android_kernel_samsung_universal7420` 里查：

```
origin/lineage-20                      24266d1a3e8  ← 正好就是这个 commit
origin/lineage-20.0-bpf-v2             6e7611af905  (2025-06-25  defconfig: spoof kernel version)
origin/lineage-20.0-unify-clang-v3     ce1b5103a50  (2026-01-10)
origin/lineage-21.0-bpf-alpha          （含完整 eBPF 回移）
```

⇒ **`lineage-20.0-20260409` 的 ROM 内核取自 `lineage-20` 分支。**

### 4.2 该分支缺什么

```python
# kernel/bpf/syscall.c @ origin/lineage-20
switch (cmd) {
case BPF_MAP_CREATE: ... case BPF_PROG_LOAD: ...
case BPF_OBJ_PIN:    ... case BPF_OBJ_GET:    ...
#ifdef CONFIG_CGROUP_BPF
case BPF_PROG_ATTACH: ... case BPF_PROG_DETACH: ...
#endif
default: err = -EINVAL;      # ← BPF_OBJ_GET_INFO_BY_FD 落在这里
}
```

- 全树 grep `bpf_obj_get_info_by_fd` → **0 命中**（`lineage-20` 分支）
- 对比：`lineage-21.0-bpf-alpha` 有 `bpf_obj_get_info_by_fd()` + `BPF_OBJ_GET_INFO_BY_FD` case
- defconfig 里 `CONFIG_BPF=y / CONFIG_BPF_SYSCALL=y / CONFIG_BPF_JIT=y / CONFIG_CGROUP_BPF=y` **都开着**
  —— 所以内核里**有** BPF 字符串（这就是为什么"看符号像是有 eBPF"会误判），
  但**缺去重用的 info 查询接口**。

### 4.3 为什么这直接导致起不来

LOS 20 system 镜像实测（`los20sys/system.img`，debugfs 读取）：

```
/system/etc/init/bpfloader.rc:
  on load_bpf_programs
      write /proc/sys/kernel/unprivileged_bpf_disabled 0
      write /proc/sys/net/core/bpf_jit_enable 1
      write /proc/sys/net/core/bpf_jit_kallsyms 1
      exec_start bpfloader
  service bpfloader /system/bin/bpfloader
      rlimit memlock 1073741824 1073741824
      reboot_on_failure reboot,bpfloader-failed     ← 失败即重启
```

- `/system/etc/bpf/` 只有 4 个程序：`fuse_media.o`、`gpu_mem.o`、`gpu_work.o`、`time_in_state.o`
- 关键的 `netd.o` / tethering `offload.o` 在 **`/system/apex/com.android.tethering`** 里（实测存在）
- Android 13 里 Tethering 的 BPF 程序是**关键程序**，加载失败 → `bpfloader` 退出非 0
  → `reboot_on_failure` → **重启**

这与 §8.2 记录的现场症状完全吻合：

```
开 JIT   → tethering offload.o 加载时挂死（LibBpfLoader: applying relo 之后静止）
关 JIT   → offload.o 过了，接着 netd.o 建 map 时 EPERM
根因     → bpf_obj_get_info_by_fd 缺失 → 去重失效 → 程序被反复加载 → locked_vm 顶爆
```

**⇒ 这三个观测（源码、system 镜像、现场日志）互相独立且完全一致。可以下定论：现成包刷上去必然重启循环。**

---

## 五、出路（按代价从低到高）

### 路线 A：改 system 镜像里的 `bpfloader.rc`（最快，半天）
把 `bpfloader.rc` 改成 bpfloader 自己注释里写的"调试姿势"：
- `bpf_jit_enable 0`（绕开 offload.o 挂死）
- 注释掉 `reboot_on_failure reboot,bpfloader-failed`（不让它重启）

预期：系统能进 Android 13，但 **netd 的 BPF 相关功能（数据统计/防火墙/tethering）降级或不可用**，
Wi-Fi 本身走 wpa_supplicant + 内核 netlink，**大概率可用**。
代价：需要改 system 镜像并重新打包 ROM（`los20sys/system.img` 已解出，可直接改再转回 `system.new.dat.br`）。

### 路线 B：换内核（干净，1–3 天）
用 `lineage-21.0-bpf-alpha` 里的 **eBPF 回移补丁**（含 `bpf_obj_get_info_by_fd` + memlock 记账修正）
打到 LOS 20 内核上，重新编译内核、重打包 boot.img。
风险：该分支标注 alpha；需自行验证与 LOS 20 设备树的兼容性。

### 路线 C：问维护者要一个带 eBPF 回移的 LOS 20 包（最省事）
`lineage-20.0-bpf-v2` 分支（2025-06-25）标题是 "defconfig: spoof kernel version"，
说明维护者在做 eBPF 方向的工作；XDA 帖（[LOS 20 S6](https://xdaforums.com/t/rom-unofficial-13-0-lineageos-20.4586295/)）
可以问"ctc 变体 + eBPF 支持"的进度。

---

## 六、操作路径（审批后执行）

### 6.1 装回 TWRP（必须，当前设备上没有）
```bash
# TWRP 3.7.0-9-2 (fakeman 版，zeroflte)
curl -LO https://github.com/fakemanoan/TWRP-Releases/releases/download/TWRP_3.7.0-9-2/TWRP_3.7.0-9-2-fakeman_zeroflte.img
adb push TWRP...img /data/local/tmp/
adb shell 'su -c "dd if=/data/local/tmp/TWRP...img of=/dev/block/by-name/RECOVERY"'
adb shell 'su -c "sync"'
adb reboot recovery
```

### 6.2 备份（升级前的回滚保障）
- `BOOT` 分区镜像（当前可直接 `dd` 出来，29,360,128 B，已在 `twrp-backup-20260929/BOOT-los181-current.img`）
- LOS 18.1 原版 `boot.img`（`roms/boot-18.1.img`）+ 修复版（`roms/boot-los181-touchfix.img`）
- `/data` 全量镜像（12 GB，USB 有线传输约 20–30 分钟；`twrp-backup-*` 里那份 28 GB 是**原厂 A7** 的，不是现在的）
- 回滚只需 `dd` 回 boot 分区 + 重刷 LOS 18.1 system —— **/data 不受影响**

### 6.3 刷机顺序（保留数据）
```
1) 进 TWRP（Power + VolUp + Home），拔掉 USB 线再重启
2) 不 format data、不 wipe data —— 只让 ROM 自己覆盖 /system
3) Install → lineage-20.0-<含触摸修复>.zip
4) Install → MindTheGapps_Legacy-13.0.0-arm64-*.zip
5) 重启（首次开机 3–5 分钟）
```

---

## 七、待确认事项

1. 路线 A（改 `bpfloader.rc`）的实际效果 —— 需要真机验证；我无法在本地模拟 3.10 内核 + Android 13 的 bpfloader 行为。
2. `lineage-21.0-bpf-alpha` 的 eBPF 回移能否干净地移植到 LOS 20 内核（需试编译）。
3. 保留数据升级后，Android 11 → 13 的应用兼容性（个别应用的 `targetSdk` 相关行为变化）——
   这不影响能否开机，只影响个别应用。

---

## 八、本次产出

| 文件 | 说明 |
|---|---|
| `los20-work/fix_boot.py` | boot.img 触摸修复打补丁器（含自检、回读校验） |
| `los20-work/boot-20.0-touchfix.img` | **已打好触摸修复的 LOS 20 boot 镜像** |
| `los20-work/boot-20.0.img` | LOS 20 原版 boot（对照） |
| `los20-work/dtb-rom/`、`dtb-rom20/`、`dtb-cur/` | 各版本 DTB 提取件（EUR/CHN 对照） |
| `los20sys/system.img` | LOS 20 system 镜像（ext4，可 debugfs 直接读） |
| 本文 | 调研与实施记录 |
