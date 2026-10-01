# KernelSU 32651 集成说明（SM-G9209 / 内核 3.10.108）

## 为什么不能用官方 KernelSU

| 方案 | 结论 |
|---|---|
| 官方 `tiann/KernelSU`（含 v3.3.0） | ❌ **GKI-only**，无任何 3.x/4.x 兼容代码 |
| Manager v3.3.0 | ❌ 界面直接显示"不支持，只支持 GKI 内核" |
| **`backslashxx/KernelSU`** | ✅ **唯一持续支持 k3.0 ~ mainline 的分支** |

`backslashxx/KernelSU` 的 `kernel/INTERNAL.md` 明确写道：

```
## hooking
- wired up for aarch64 and armeabi, k3.0 ~ mainline (7.2 as of current)
- syscall table hooking is implemented
- manual hooking is still supported and will be kept forever.

## LSM framework
- 3.x LSM scans the whole kernel to hunt for selinux_ops.
```

## 内核侧集成（3 处修改）

### ① 替换驱动

```bash
rm -rf drivers/kernelsu
cp -a /path/to/backslashxx-KernelSU/kernel drivers/kernelsu
```

版本：`drivers/kernelsu/Makefile` → `-DKSU_VERSION=32651`

### ② defconfig

```
CONFIG_KSU=y
CONFIG_KSU_KPROBES_KSUD=y
CONFIG_KSU_FEATURE_ADBROOT=y
# CONFIG_KSU_DEBUG is not set
# CONFIG_KSU_LSM_SECURITY_HOOKS is not set
# CONFIG_KSU_THRONE_TRACKER_ALWAYS_THREADED is not set
```

> ⚠️ 旧的 KSU 选项（`KSU_KRETPROBES_SUCOMPAT`、`KSU_ALLOWLIST_WORKAROUND`、
> `KSU_THRONE_TRACKER_ALWAYS_THREADED` 等）在新版里已改名/移除，必须清掉。

### ③ 兼容桩 `compat_hooks_3_10.c`

本内核源码里已被**旧版 KernelSU** 打过「手工 hook」补丁（提交
`6946f20fcb4`、`3a82639b407`），在 `security/security.c`、`drivers/input/input.c`、
`fs/read_write.c`、`security/selinux/hooks.c` 里直接调用 `ksu_*` 函数。

新版驱动自己做动态 hook，不需要这些调用点，所以给缺失的符号提供**空实现**
（见 `compat_hooks_3_10.c`），并把它 `#include` 到 `drivers/kernelsu/ksu.c` 末尾。

### ④ ⚠️ 最关键的一步：`security_file_permission` 必须调用 `ksu_file_permission`

**这是整件事的命门。**

因为 `CONFIG_KSU_LSM_SECURITY_HOOKS` 关闭，驱动走的是
`hook/lsm_hooks_manual.c` 路径，其中：

```c
int ksu_file_permission(struct file *file, int mask)
{
    if (unlikely(ksu_vfs_read_hook))
        ksu_install_rc_hook(file);      // ← 触发 apply_kernelsu_rules()
    return 0;
}
```

`ksu_install_rc_hook()` 在检测到 init 读取 `init.rc` 时调用
`apply_kernelsu_rules()` —— **这是 `u:r:ksu:s0` 域被创建的唯一途径**。

而内核源码里的旧集成调用的是**另一套函数名**，`ksu_file_permission` 从来没人调：

| 内核旧调用点 | 新驱动实际函数 | 修法 |
|---|---|---|
| `ksu_inode_permission` | 已移除 | 删掉调用 |
| `ksu_handle_rename(d,d)` | `ksu_inode_rename(inode,d,inode,d)` | 改签名 |
| `ksu_handle_setuid(new,old)` | `ksu_task_fix_setuid(new,old,flags)` | 改签名 |
| **（完全没有）** | **`ksu_file_permission(file,mask)`** | **新增调用** |

补丁见 `kernel-patches/0001-ksu-hook-callsites-fix.patch`。

### ⑤ `ksud.h` 声明冲突

`drivers/kernelsu/runtime/ksud.h` 里 `ksu_vfs_read_hook` / `ksu_input_hook`
声明为 `static`，但内核其它文件要 `extern` 引用它们 → 改成 `extern`，
并在 `runtime/ksud.c` 里去掉定义处的 `static`。

## 症状对照表

| 症状 | 原因 |
|---|---|
| Manager 显示"不支持，只支持 GKI 内核" | `ksu` 域不存在（`apply_kernelsu_rules` 没跑） |
| `KernelSU: security_secctx_to_secid u:r:ksu:s0 -> error: -22` | 同上 |
| `KernelSU: transive domain failed` | 同上 |
| `KernelSU: is_manager: 0`（所有应用） | 同上 |
| 修复后 | `is_manager: 1` + `Crowning manager` + Manager 显示"工作中" |

## userspace（ksud + Manager）

内核只提供 root 能力，`ksud` 与 Manager 需另外编译：

```bash
# ksud（Rust）
python3 scripts/setup_cargo_config.py     # 生成 .cargo/config.toml，需要 NDK
cargo build --release --target aarch64-linux-android -p ksud
# 产物 → /data/adb/ksud  (权限 0755, 属主 0:0)

# Manager（Gradle）
cd manager
echo "sdk.dir=$ANDROID_HOME" > local.properties
cat >> gradle.properties <<'X'
KEYSTORE_PASSWORD=password
KEY_ALIAS=alias
KEY_PASSWORD=password
KEYSTORE_FILE=dummy.keystore
X
./gradlew clean assembleRelease
```

**构建要求**：compileSdk 37 / buildTools 37.0.0 / NDK 29.0.14206865 /
Gradle 9.7.1 / JDK 21 / Rust `aarch64-linux-android` target。

> ⚠️ **坑**：若 `~/.gradle/gradle.properties` 里有全局代理配置
> （`systemProp.https.proxyHost=...`），会导致 maven 仓库全部返回 **403**。
> 直连反而正常 —— 编译前先确认没有代理配置。

## 签名

内核白名单（`manager/apk_sign.c`）只认这几个证书，且 **APK 必须只有 v2 签名**
（含 v3/v3.1 会被拒）：

```c
0x363 "4359c171f32543394cbc23ef908c4bb94cad7c8087002ba164c8230948c21549"  // dummy.keystore
0x33b "c371061b19d8c7d7d6133c6a9bafe198fa944e50c1b31c9d8daa8d7f1fc2d2d6"  // ksu official
0x375 "484fcba6e6c43b1fb09700633bf2fb4758f13cb0b2f4457b80d075084b26c588"  // KOWX712
```

仓库自带的 `manager/dummy.keystore`（口令 `password` / 别名 `alias`）即第一个，
**内核认它**，所以用仓库默认配置编译出的 Manager 可以直接被识别。

## 为什么不用 Magisk

`magiskboot` 处理不了三星的 **DHTB** 设备树封装（`extra` 不是裸 FDT，
而是 DHTB 表 + 多个 DTB 条目），`magiskboot dtb extra test` 失败导致
`boot_patch.sh` abort。即使绕过该步、用 `repack_boot_magisk.py` 精确重打包
（kernel/DTB 逐字节相同、只换 ramdisk），也会卡第一屏无红字 ——
`magiskinit` 替换链在本机的 `skip_initramfs` 引导流程下走不通。

**结论：这台设备只能用 KernelSU。**

---

## ⚠️ 补充：Manager APK 必须「重新打包」才能用

Gradle 直接编出来的 APK **没有 `libksud.so`**，Manager 会报：

```
W KsuCli: Cannot run program ".../lib/arm64/libksud.so": error=2, No such file or directory
```

新版 Manager 把 ksud 当作**原生库**（`libksud.so`）使用，必须用仓库的
`repack_apk.py` 把 ksud 注入进去并重签名：

```bash
cd /path/to/backslashxx-KernelSU
python3 repack_apk.py repack \
  -b release -t release \
  -a arm64-v8a \
  -K manager/dummy.keystore \
  -A alias -P password -S password \
  --strip
# 产物: dist/KernelSU_<version>_<code>-release.apk
```

这一步在 CI 里是独立的 `repack-manager` job（依赖 build-manager + build-ksud）。

**验证注入成功**：
```bash
unzip -l dist/KernelSU_*.apk | grep libksud
# 应看到 lib/arm64-v8a/libksud.so
```

**验证运行正常**（Manager 启动后看 logcat）：
```
I KernelSU: ksud::cli: command: Feature { command: Check { id: "kernel_umount" } }
```
