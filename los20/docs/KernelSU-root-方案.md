# KernelSU root 方案（SM-G9209 / LineageOS 20）—— 已成功

日期：2026-10-01
状态：✅ **root 已恢复可用**

---

## 结论先行

**这台设备的自编译内核里本来就有 KernelSU**（`CONFIG_KSU=y`），
根本不需要 Magisk！之前 root 不可用只是**没装匹配的 Manager 应用**。

---

## 关键发现过程

### 1. 内核里有 KernelSU（dmesg 证据）
```
KernelSU: track_throne_function: /data/system/packages.list found!
KernelSU: Searching manager...
KernelSU: search_manager: dir: /data/app got magic! 0xef53
KernelSU: on_post_fs_data!
KernelSU: load_allow_list open file failed: -2      ← allowlist 还不存在
```
kallsyms 里也有：`ksu_show_allow_list` `ksu_get_app_profile` `ksu_set_app_profile`
`__ksu_is_allow_uid` `ksu_uid_should_umount` `ksu_get_root_profile`

### 2. 内核配置与源码位置
| 项目 | 值 |
|---|---|
| defconfig | `arch/arm64/configs/exynos7420-zeroflte_defconfig` → `CONFIG_KSU=y` |
| 源码 | `kernel/samsung/universal7420/drivers/kernelsu/` |
| 版本 | `drivers/kernelsu/Makefile` → `-DKSU_VERSION=12126` |
| 期望签名 | `KSU_EXPECTED_SIZE := 0x033b` + `KSU_EXPECTED_HASH := c371061b19d8c7d7d6133c6a9bafe198fa944e50c1b31c9d8daa8d7f1fc2d2d6` |

### 3. ⚠️ 关键坑：Manager 版本必须匹配内核
装最新的 Manager v3.2.4 (32457) 会报红字：
> 当前 KernelSU 版本 12126 过低，管理器无法正常工作，请将内核 KernelSU 版本升级至 **32377** 或以上！
> **获取 root 失败!**

（虽然底部显示"工作中 版本: 12126"，驱动是好的，但 Manager 拒绝工作）

## 各 KernelSU 发布版的 versionCode（用于配对内核）

| 发布版 | versionCode |
|---|---|
| v0.9.5 | 11872 |
| v1.0.0 | 11874 |
| v1.0.3 | 12018 |
| **v1.0.5** | **12081** ← 内核 12126 最接近的发布版 |
| v2.0.0 | 22001 |
| v3.0.0 | 32179 |
| v3.1.0 | 32302 |
| v3.2.4 | 32457 |

内核 12126 落在 v1.0.5(12081) 与 v2.0.0(22001) 之间 ——
说明社区内核算的是 KernelSU **主干开发版**（Makefile 注释：
"compliant to last upstream kernel change as of 20250925"），没有对应发布版。

**⇒ 用最接近的 v1.0.5 即可正常工作。**

---

## ✅ 解决方案（已执行成功）

```bash
# 1. 下载匹配内核 12126 的旧版 Manager
curl -L -o KernelSU_v1.0.5_12081-release.apk \
  https://github.com/tiann/KernelSU/releases/download/v1.0.5/KernelSU_v1.0.5_12081-release.apk

# 2. 安装（降级覆盖新版）
adb install -r -d KernelSU_v1.0.5_12081-release.apk

# 3. 启动一次，让 KernelSU 的 throne_tracker 发现 Manager
adb shell monkey -p me.weishu.kernelsu -c android.intent.category.LAUNCHER 1
```

### 签名校验（内核只认这几个）
内核 `apk_sign.c` 白名单（`check_v2_signature`）：
```c
0x363 "4359c171..."  // dummy.keystore
0x33b "c371061b19d8c7d7d6133c6a9bafe198fa944e50c1b31c9d8daa8d7f1fc2d2d6"  // ksu official
384   "7e0c6d72..."  // 5ec1cff/KernelSU
0x375 "484fcba6..."  // KOWX712/KernelSU
0x396 "f415f4ed..."  // rsuntk/KernelSU
0x3e6 "79e59011..."  // rifsxd/KernelSU-Next
0x35c "947ae944..."  // ShirkNeko/SukiSU-Ultra
```
**另外 APK 必须只有 v2 签名**（有 v3/v3.1 会被直接拒绝）。

官方 KernelSU 发布版全部满足：证书长度 827 (0x33b) + SHA256 = `c371061b...`

---

## 验证结果

Manager 主页显示（**无红字**）：
```
✅ 工作中
   版本: 12126
   超级用户数: 1
   模块数: 4
内核版本: 3.10.108-g1de3d6e1144-dirty
管理器版本: v1.0.5 (12081)
SELinux 状态: 宽容模式
```

**root 生效的硬证据**：`/data/adb/` 权限是 `drwx------ root root`
（普通应用读不了），但 Manager 却能列出"模块数: 4"和超级用户列表
⇒ Manager 确实通过 KernelSU 拿到了 root。

### 设备上的关键路径
| 路径 | 说明 |
|---|---|
| `/data/adb/ksu/.allowlist` | 已授权列表（**按包名存储**，format v3） |
| `/data/adb/ksu/bin/` | `ksud` `busybox` `resetprop` `magiskboot` `bootctl` |
| `/data/adb/ksud` | ksud 主程序（3,318,496 字节） |
| `/data/adb/modules/` | 4 个模块（见下） |
| `/system/bin/su` | **内核伪造的**（`ls` 看得到、读不到内容）—— 正常现象 |

### 已授权的应用
- `bin.mt.plus`（MT管理器）← 已授权

### 4 个模块（文件完好，但都被禁用）
| 模块 | 名称 | 状态 |
|---|---|---|
| `asoul_affinity_opt` | A-SOUL Games Optimization (Kana) | 有 `disable` 文件 |
| `scene_swap_controller` | Scene的附加模块(二) v4.2.4 | 有 `disable` 文件 |
| `scene_thermal_remover` | [SCENE]ThermalRemover v1.0.0 | 有 `disable` 文件 |
| `uperf` | Uperf Game Turbo v1.51 | 有 `disable` 文件 |

⇒ 想启用就去 KernelSU Manager → 模块 → 打开开关（或删除对应目录下的 `disable` 文件后重启）

---

## ❌ 为什么 Magisk 走不通（3 次尝试全失败，留档）

| 尝试 | 结果 |
|---|---|
| TWRP 直刷 `Magisk-v30.7.apk` | `magiskboot dtb extra test` 失败 → `boot_patch.sh` abort |
| 设备端 magiskboot 手工 patch ramdisk + 宿主机重打包 | 结构验证全绿（kernel/DTB 逐字节相同、只换 ramdisk），但**卡第一屏无红字** |
| 从干净基线精确重打包 | 同上，仍卡第一屏 |

**根因**：Magisk 的 `magiskboot` 无法处理三星的 **DHTB** 设备树封装
（`extra` 不是裸 FDT，而是 DHTB 表 + 多个 DTB 条目）。
即使绕过该步、结构完全正确，Magisk 的 `magiskinit` 替换链在这台机器的
`skip_initramfs` 引导流程下也走不通。

**结论**：这台设备应该用 **KernelSU**（内核态方案，不动 ramdisk），不要用 Magisk。

---

## 🔧 相关工具（本次写的）
| 文件 | 用途 |
|---|---|
| `los20-work/repack_boot_magisk.py` | 三星 DHTB 格式的 boot 重打包（含自检） |
| `los20-work/magiskpatch/` | Magisk 尝试的中间产物（留档） |
| `los20-work/boot-built-romdtb-touchfix2.img` | **当前可用 boot**（自编译内核 + 触摸修复） |

## ⚠️ 回滚命令（备用）
```bash
adb push boot-built-romdtb-touchfix2.img /data/local/tmp/boot-good.img
adb shell "dd if=/data/local/tmp/boot-good.img of=/dev/block/by-name/BOOT bs=4096"
adb reboot
```
