# 发布指南（XDA / GitHub）

## 一、GitHub 仓库建议

仓库名：`zerofltectc-los181-fix`（或并入你的 S6 项目仓库）
直接上传本目录全部内容，`README.md` 已写好（含中文正文 + 英文 TL;DR）。

发布 Release：
- Tag: `v1.0`
- 附件: `zerofltectc-los181-fix-v1.0.zip`
- Release notes 可直接用下面 XDA 模板的英文部分

## 二、XDA 帖子模板

**标题**：`[FIX] SM-G9209 (zerofltectc / China Telecom) — boot loop + dead touchscreen fix for LineageOS 18.1`

**正文（英文）**：

> **Device**: Galaxy S6 SM-G9209 (China Telecom, `zerofltectc`) only.
> **Base ROM**: `lineage-18.1-*-UNOFFICIAL-zeroflte.zip`
>
> If you flash the community LineageOS 18.1 on an SM-G9209, it boot-loops forever and the
> touchscreen never works (even in TWRP). Root cause: the kernel ships only the **EUR** device tree
> for this board, where the `s2mpb02` PMIC is on the wrong I²C bus, so the `tsp_avdd` regulator never
> registers → the touch controller is never powered → the touch HAL never registers `IStylusMode` →
> `system_server`'s main thread blocks in `HwBinder.getService()` and the watchdog kills it every
> ~100 s. A second bug: the touch HAL's init rc is missing from the ROM.
>
> **This 8 MB zip fixes both** (patched DTB in the boot image + the missing rc).
>
> **Install**: TWRP → Install → `zerofltectc-los181-fix-v1.0.zip` → Reboot System (unplug USB first).
> Script validates the model, backs up your current boot to `/sdcard/boot-backup-before-fix.img`.
>
> **Verify**: `grep sec_touchscreen /proc/bus/input/devices` and `getprop sys.boot_completed` → `1`.
>
> **Known limits**: cellular does not work on this variant (Qualcomm MDM9635M modem isn't supported
> by the community trees), no VoLTE. Use as a Wi-Fi device. Android 13 (LOS 20) additionally has an
> eBPF issue and is not covered.
>
> **Upstream fix for maintainers**: add the existing `exynos7420-zeroflte_chn_*.dtb` to the
> `CONFIG_BOARD_ZEROFLTE` dtb list (with stock board revisions rev04→7, rev05→8, rev06a→9,
> rev06→10, rev07→0) and ship the touch HAL's init rc. Details in `upstream/ISSUE.md`.

## 三、发布前检查清单

- [ ] 已在自己的 SM-G9209 上刷过 `zerofltectc-los181-fix-v1.0.zip` 并成功开机（建议做一次验证）
- [ ] 已确认 `SHA256SUMS.txt` 与 zip 一致
- [ ] 已在帖子中注明**仅适用 SM-G9209**、以及电信卡不可用的限制
- [ ] 若同时发布 boot 镜像单独文件，注明"仅供 LOS 18.1 基座使用"

## 四、可选后续

* 把 `upstream/ISSUE.md` 提成 issue 给 [samsungexynos7420](https://github.com/samsungexynos7420)（DTB 列表 + rc 两处）
* 若想让 G9209 用上 Android 13：还需解决 eBPF（`bpf_obj_get_info_by_fd` 实现 + memlock 记账）
* 想要"一个包直接刷完"的完整 ROM（把 rc 烘进 system 镜像），可以基于官方 zip 做 `system.new.dat.br`
  重打包 —— 需要时我可以生成
