# [zerofltectc / SM-G9209] Boot loop + dead touchscreen — DTB table ships only EUR variants; touch HAL init rc missing

**Device**: Samsung Galaxy S6 SM-G9209 (China Telecom), codename `zerofltectc`, bootloader `G9209KEU2ERI2`, `hw_rev=10`
**ROM**: `lineage-18.1-20260415-UNOFFICIAL-zeroflte.zip` (also reproduces on the LOS 20 build)
**Recovery**: TWRP 3.7.0_9-2-fakeman
**Kernel branch**: `lineage-18.1-unify-clang`

## Symptoms
* Boot animation plays forever; never reaches the UI.
* `system_server` is killed by the watchdog roughly every 100 s and restarted.
* The touchscreen never works at all — not even in TWRP (only the capacitive keys do).
* (LOS 20 additionally: `init` blocks in `bpfloader`, USB never enumerates.)

## Root cause 1 — wrong DTB variant for this board

The kernel image is built with only the **EUR** device trees, so this China Telecom board ends up on
`Samsung ZERO-F LTE EUR rev06`:

```
$ cat /proc/device-tree/model
Samsung ZERO-F LTE EUR rev06 board based on Exynos7420(EVT1), mPOP     # stock uses ZERO-F LTE CHN
```

In the EUR DTS the `s2mpb02` PMIC is placed on `hsi2c@14E60000`, but on this board it lives on
`hsi2c@13670000` (as in the stock CHN dtb and — notably — **as already written in your own
`exynos7420-zeroflte_chn_00.dts`**):

```dts
/* exynos7420-zeroflte_chn_00.dts (correct) */
hsi2c@13670000 { ... s2mpb02@59 { /* tsp_avdd = s2mpb02-ldo17 */ } }
```
```dts
/* exynos7420-zeroflte_eur_open_06.dts (what the device actually boots) */
hsi2c@13670000 { max77838@60 { ... } }
hsi2c@14E60000 { ... s2mpb02@59 { ... } }      /* wrong bus for CTC */
```

Consequences in dmesg:
```
s2mpb02_i2c_probe: device not found on this channel!!
fts_touch 7-0049: fts_power_ctrl: Failed to get tsp_avdd regulator.
fts_touch 7-0049: fts_read_chip_id failed. ret: -121
fts_touch: probe of 7-0049 failed with error 1
```
→ no touchscreen input device is created (`/proc/bus/input/devices` lists only `sec_touchkey`).

## Root cause 2 — touch HAL init rc is not installed

`vendor.lineage.touch@1.0-service.samsung` exists in `/vendor/bin/hw/`, its SELinux domain
(`hal_lineage_touch_default_exec`), hwservice label and even `IStylusMode` in
`vendor_hwservice_contexts` are all present — but **no rc file starts the service**
(other lineage HALs such as `livedisplay`, `fastcharge`, `trust` all ship one).

## Root cause 3 — the framework blocks on the missing interface

```
init: Could not find 'vendor.lineage.touch@1.0::IStylusMode/default' for ctl.interface_start
```
and `system_server` main thread (from `/data/system/dropbox/system_server_watchdog@*.txt.gz`):
```
"main" prio=5 tid=1 Native
  at android.os.HwBinder.getService(Native method)
  at vendor.lineage.touch.V1_0.IStylusMode.getService(IStylusMode.java:55)
  at lineageos.hardware.LineageHardwareManager.getHIDLService(LineageHardwareManager.java:308)
  at com.android.server.inputmethod.InputMethodManagerService.updateTouchHovering(InputMethodManagerService.java:3113)
  at com.android.server.SystemServer.startOtherServices(SystemServer.java:2265)
```
→ 60 s watchdog timeout → `system_server` killed → `zygote` restart → endless boot animation.

## Suggested fixes

1. `arch/arm64/boot/dts/Makefile`: add the CHN variants to the `CONFIG_BOARD_ZEROFLTE` dtb list
   (the sources already exist), and give the DTB-table entries the board revisions from the stock
   table: rev04→7, rev05→8, rev06a→9, rev06→10, rev07→0. `hw_rev=10` devices (CTC) will then pick
   `ZERO-F LTE CHN rev06`, which has the correct touch power rails.
2. Install `vendor.lineage.touch@1.0-service.samsung.rc` with the HAL (should ship with the binary).
3. Optional hardening: `LineageHardwareManager.isSupported()` / `IMMS.updateTouchHovering()` use a
   **blocking** `HwBinder.getService()`; using the non-blocking variant (or guarding on a device
   feature) would avoid a 60 s main-thread stall whenever a touch HAL is absent/partial.

## Verified fix
Replacing the boot image's DTB table with a patched EUR DTB (node `s2mpb02@59` moved from
`hsi2c@14E60000` to `hsi2c@13670000`, same DTB so phandles are unaffected) **plus** installing the
missing rc results in:
`sec_touchscreen` present, `vendor.touch-hal-1-0` running, `sys.boot_completed=1`, zero watchdog
reports, system stable >30 min.
