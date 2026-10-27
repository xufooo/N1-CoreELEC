# N1 杜比视界：P5 实验固件实现解剖与 2026 最新方案

分析日期：2026-10-26。基线：CoreELEC 21.3-Omega（`fc61125e`）+ linux-amlogic 4.9（`50c8e815`）+ Kodi（`acc0fc66`），
见 [n1-sources.md](n1-sources.md)。设备：Phicomm N1（S905D/GXL，2 GB）。

本文件只做实现与方案分析，不含任何已合入的实验补丁；固件编译与实机播放仍未通过（见 [n1-acceptance.md](n1-acceptance.md)）。

---

## 0. 结论先行

1. **N1（S905X / meson-gxl）在本项目锁定的 4.9 内核里被杜比视界引擎显式排除**：`chip_support_dv()` 只认
   `meson-txlx / gxm / g12 / tm2 / sc2`，而 `dolby_vision_addr()` 也只给这些芯片分配 DV Core 寄存器基址
   → **GXL 芯片里没有重塑引擎这块硬件**。
2. 杜比授权 blob（`dovi.ko`）只存在于 `-J/-K` 后缀授权机型（S905X2-J/K、S905X4-J/K、S922X-J/K、S905X5-J/K 等），
   从其原厂 Android 固件中提取；N1 自身 Android（slimBoxTv 9.20）不带 DV，无 blob 可取。
3. **"硬件不够"与"没授权"在 N1 上是同一件事的两面**：授权名单恰好覆盖有 DV Core 的芯片代次（G12/TXL/TM2/SC2），
   GXL 两样都没有。因此不是"补一个授权就能开"的情况。
4. **但输出段可以绕（见 §5）**：HDMI TX 的 VSIF/EMP 注入路径门槛是 `chip_type >= MESON_CPU_ID_GXL`（下界制），
   **GXL 恰好在支持侧**；两条注入路径（`send_emp()` 的 EMP/VSEM、`hdmitx_set_vsif_pkt()` 的 HDMI 1.4b VSIF）
   都不需要杜比授权。→ **P8 的 TV-led 真 DV（电视用 RPU 自行重塑）在原理上可行**，代价是自己实现注入。
5. 绕不过去的是**盒子端重塑本身**：Player-led、FEL 合成需要 DV Core + 授权 blob → 不可能。
   但**电视端重塑（TV-led）可以绕过**：按 §5.0 的原理（把 L1/L2 元数据内嵌进 12bit 4:2:2 输出的顶部像素 +
   发 Dolby VSIF/AVI），**P8 与 P5（P5 需先合成 RPU）都能出真 DV，且不需要 DV Core、不需要授权 blob**。
   基线内核已含 TV-led 的 VSIF/AVI 侧接口（`dovi_tv_led_bt2020` / `dovi_tv_led_no_colorimetry` / `SET_AVI_NO_CM`）。
6. **CoreELEC 22.0-Piers 已明确放弃 GXL（S905X）及更早机型**，官方路线在 N1 上不会再有 DV。
7. 2026 年最完整、最新的 NG 杜比实现是 **avdvplus R10（2026-09-06）**：`CoreELEC NG 21.3` +
   `linux-amlogic 4.9 (amlogic-4.9-20-cpm)` + `Kodi aml-4.9-21.3-cpm` + `dovi5-prepare`（含 `dv_compat_shim`）。
   它是**授权 SoC** 的方案；其 Kodi 侧转换/设置逻辑可单独回移到 N1 分支。

### 0.1 能力矩阵（按"缺哪一样"分解）

| 目标 | 需要 DV Core 硬件 | 需要杜比授权 blob | N1(GXL) 结论 |
|---|---|---|---|
| P8 → **TV-led 真 DV**（VSIF/RPU 注入，电视自行重塑） | 否 | 否 | **原理可行**，需自己实现注入 + 实机验证 |
| P8 → Player-led（盒子自己重塑） | 是 | 是 | ✗ |
| P8 → 干净 HDR10（剥离 RPU） | 否 | 否 | ✅ 简单可做（路线 A，与 TV-led 互斥） |
| **P5 → 正确色彩（TV-led：先合成 RPU 再内嵌元数据）** | 否（电视重塑） | 否 | **原理可行**，但需元数据合成 + 内嵌写入 |
| P5 → 软件 VS10（DV→HDR10） | 否 | 否 | ✅ 可做（路线 B） |
| P7 MEL/FEL | 是 | 是 | ✗（可退化为 BL+HDR10） |
| HDR10 → DV CMv4.0 合成 | 是 | 是 | ✗ |

---

## 1. 已读上下文

- 本目录文档：`README.md`、`docs/n1-build.md`、`docs/n1-sources.md`、`docs/n1-patch-review.md`、`docs/n1-acceptance.md`。
  现有结论是"当前不把任何 DV 代码合入基础版"，验收要求 P5 / P8.1 / P7 MEL 分开测，
  并明确"不要以 DV 徽标作为重塑正确的证据"。
- 前期会话记录中的 N1 补丁栈审计、工厂 MAC 传递、NTFS helper 冲突修复等结论已在
  `docs/n1-patch-review.md` 中落盘；DV 尚未合入（截至本报告写作时）。

---

## 2. P5 实验固件（2025-12）的实现解剖

### 2.1 事实基线

来源：[CoreELEC 论坛 "Dolby Vision for all SoCs"（57985）](https://discourse.coreelec.org/t/dolby-vision-for-all-socs/57985)，
本地留档 `.work/research/dv-thread.json`（16 帖，末帖 2026-02-21）。

- 作者 doppingkoala 于 2025-12-14 发布"新增 profile 5 支持、仅缺 FEL"的构建，**基于 CoreELEC 21.1**。
- 反馈：Odroid N2（S905X2/G12B）与 T95Q（S905X3）可播 DV；S905X3 的 P8 起播 2–3 秒后黑屏；
  P7 FEL 会让电视在 HDR10/DV 间来回切换（显示源类型仍报 HDR、EOTF 报 DV-Std）。
- 2026-02-21 作者说明：CE-NO（5.15）路线因性能（Wi-Fi/eMMC 降到 1/8）暂停；
  已想到"绕过 Kodi GUI 层加 metadata"的更优方案，但未继续；FEL 需要第二个视频解码器，也未推进。
- **此后无更新**：作者仓库分支最新提交仍停在 2026-02/2024（见 §5.3）。

### 2.2 代码溯源（本地 `.work/research/` 已抓取）

| 仓库/分支 | 提交 | 实际内容 | 对 N1 的适用性 |
|---|---|---|---|
| `xbmc:dv-doppingkoala-21.2` | `cd832d4f` | 相对作者自己的 `aml-4.9-21.2` **只有 1 个皮肤文件改动** | 分支名不能当作 P5 实现证据 |
| `xbmc:public_dv_pov` | `ce7c6c62` (2026-02-23) | Kodi 侧 DRM YUV overlay：`drm_mode_create_dumb` 建 3840×4 缓冲、**硬编码 plane id 44**、`zpos=128`；`rsync command` 文件显示作者基线是 CE-22 NO | NG 4.9 **没有** `xbmc/windowing/amlogic/AMLDisplay.cpp`，不可 cherry-pick；这是 CE-NO 的 GUI/OSD 绕行方案 |
| `common_drivers:public_dv_poc` | `e13ba110` (2026-01-03) | 内核侧新增 `drivers/media/video_sink/dv_injection.c`（解析 DV SEI `0x7C 0x01 0xFF`，组装 L1/L2 DM 元数据并注入 HDMI VSIF，含 CMv4.0 阈值常量）；改 `meson_hdmi.c`（YUV444→YUV422、24b→36b 色深）、`meson_plane.c`（双 OSD plane 互换）、`amcsc_pip.c`（`hdmi_packet_process()` 增加 `dv_metadata` 形参 + `should_block_vsif()` 抑制普通 VSIF） | 路径属于 5.15 CE-NO；4.9 对应文件是 `drivers/amlogic/media/enhancement/amvecm/amcsc_pip.c`（函数结构相同），**结构可移植，但 GXL 缺 DV 硬件** |
| `xbmc:aml-4.9-21.1` | 2024-08 批次 | **NG 4.9 真正的 P5 路径**：`AMLCodec: convert DV profile 5 on none DV display to HDR10 or SDR`、`libdovi: change default conversion to Lossless for Amlogic-ng-dv`、`DVDVideoCodecAmlogic: combine Dolby Vision base and enhancement layer packages`（MEL/FEL 合并）、`dolby_vision_ll_policy`、`force player led` | Kodi 侧 libdovi 处理 + Amlogic DV composer 输出；GXL 缺 composer |

**结论**：P5 实验固件 = "Kodi 侧用 libdovi 处理 DV 码流（P5→HDR10/SDR、P7→P8.1、BL+EL 合并）" +
"Amlogic `amdolby_vision` composer 做 DV 输出 + HDMI VSIF 注入"。**P5 能播的前提是 SoC 在 `chip_support_dv()` 白名单内**。

### 2.3 4.9（NG）杜比栈的完整构成

来自本项目锁定的 `CoreELEC/linux-amlogic @50c8e815` 与 `avdvplus/linux-amlogic @amlogic-4.9-20-cpm`：

- 内核：
  - `drivers/amlogic/media/enhancement/amdolby_vision/amdolby_vision.c`（composer：`dm_reg_ipcore1`、`composer_reg_ipcore`；
    sysfs `/sys/class/amdolby_vision/support_info`；模块参数 `dolby_vision_mode/policy/profile/ll_policy`、
    `dv_ll_output_mode`、`xbmc_dv_l11_vsif`、`xbmc_dv_vsvdb_inject`、`xbmc_dv_hdr10_for_dv_ll`、`force_mel`）。
  - `drivers/amlogic/media/vout/hdmitx/hdmi_tx_20/dv_emp_vsem.c`（VSIF/EMP 元数据注入，CRC32 + 128B 分包）。
  - `drivers/amlogic/dolby_fw/`（Dolby 固件装载）、`drivers/amlogic/drm/vpu-hw/meson_vpu_hdr_dv.c`。
- 用户态（**上游 21.3 基线已经具备**）：
  - `projects/Amlogic-ce/packages/multimedia/libdovi/package.mk` → dovi_tool 3.3.1 静态库，Kodi 已链接。
  - `projects/Amlogic-ce/packages/linux-drivers/amlogic/opentee_linuxdriver/` → OP-TEE 驱动 + `tee-loader` + `dovi-loader`
    （`dovi-loader.sh` 依次尝试 `/storage/.config/dovi.ko`、`/flash/dovi.ko`、`/storage/dovi.ko`、
    `/android/vendor/lib/modules/dovi.ko`、`dovi_vs10.ko`）。
  - `linux.aarch64.conf`：`CONFIG_AMLOGIC_MEDIA_ENHANCEMENT_DOLBYVISION=y`(1543)、`CONFIG_AMLOGIC_TEE=y`(1700)、
    `CONFIG_DOLBY_FW=y`(1730)；但 `options:163 TEE_SOC="S905X4"`（TA 固件仅随 S905X4 提供）。
- Kodi（`acc0fc66`）：
  - `xbmc/utils/AMLUtils.cpp:212 aml_support_dolby_vision()`：读 `/sys/class/amdolby_vision/support_info`，
    要求 `(value & 7) == 7`（无 efuse + ko 已加载 + 已更新）。
  - `xbmc/utils/BitstreamConverter.cpp processDoviRpu()`：`dovi_parse_unspec62_nalu`、`dovi_rpu_set_active_area_offsets`
    （P5「zero level 5」）、`dovi_convert_rpu_with_mode(rpu, 2)`（P7→P8.1）、`m_removeDovi` 剥离 RPU。
  - `system/settings/settings.xml:3892-3910`：`coreelec.amlogic.disabledolbyvision`、
    `coreelec.amlogic.dolbyvisionled`（TV-Led / Player-Led）、`coreelec.amlogic.dovizerolevel5`（P5）。

### 2.4 决定性证据：GXL 被排除

`linux-amlogic @50c8e815` 的 `amdolby_vision.c`：

```c
static bool chip_support_dv(void)
{
        if (is_meson_txlx() || is_meson_gxm() ||
            is_meson_g12() || is_meson_tm2() ||
            is_meson_sc2())
                return true;
        return false;
}
```

- 该文件全文 **0 次出现 `is_meson_gxl`**；`register_dv_functions()` 命中白名单外芯片时打印 `chip not support dv` 并返回失败。
- 于是 `support_info` 永远不会置位 → Kodi 的 `aml_support_dolby_vision()` 恒为 `false` → TV-Led/Player-Led 都不可用。
- `meson-gxl` = S905X / S905D / S905L，正是 N1 的 SoC；`gxm` 是 S912，`g12` 是 S905X2，`txlx` 是 S905X3，
  `tm2` 是 S922X，`sc2` 是 S928X/A1。

**更硬的证据：GXL 芯片里没有 DV 硬件块。** 同一文件的 `dolby_vision_addr()` 负责给 DV composer 的寄存器
窗口定基址，**只给白名单里的芯片赋值**：

```c
static void dolby_vision_addr(void)
{
        if (is_meson_gxm() || is_meson_g12()) { CORE1_BASE = 0x3300; CORE2A_BASE = 0x3400; CORE3_BASE = 0x3600; }
        else if (is_meson_txlx())           { CORE2A_BASE = 0x3400; CORE3_BASE = 0x3600; CORETV_BASE = 0x3300; }
        else if (is_meson_tm2())             { CORE1_BASE = 0x3300; CORE1_1_BASE = 0x4400; ... CORETV_BASE = 0x4300; }
        else if (is_meson_sc2())             { CORE1_BASE = 0x3300; CORE2A_BASE = 0x3400; CORE3_BASE = 0x3600; }
}
```

GXL 没有分支 → 所有基址保持 0 → DV composer 访问不到任何寄存器。即使把 `chip_support_dv()` 的白名单改开，
这些写操作也会落到 GXL 上无关的寄存器区域（不只是"没效果"，还有写坏别的外设的风险）。

同时 `dovi.ko` 本身只存在于杜比授权机型的原厂 Android（`-J/-K` 后缀），与社区共识一致：
"只有 -J、-K 后缀晶晨芯片具备杜比授权双解码硬件：S905X2-J、S905X4-J、S905X4-K、S922X-J"。

**因此：任何声称"N1 上跑原生 P5 杜比视界"的方案，实际只能是 VS10/HDR10 转换或伪造 DV 标记。**

---

## 3. 2026 年最新实现状态（网络核实）

### 3.1 avdvplus R10（2026-09-06）——当前最完整的 NG 杜比方案

[avdvplus/Builds R10](https://github.com/avdvplus/Builds/releases/tag/avdvplus_R10)：

- 组合：`CoreELEC-Amlogic-ng 21.3-Omega` + `linux-amlogic amlogic-4.9-20-cpm` + `media_modules-aml amlogic-4.9.269-cpm`
  + `Kodi aml-4.9-21.3-cpm`。
- 新增 `dovi5-prepare` 包（`dv5-patch-dovi.py`）：对**授权 blob** 做二进制打补丁——
  `vermagic → "4.9.269 SMP preempt mod_unload modversions aarch64"`、`depends → dv_compat_shim`、
  导出符号改名 `register_dv_functions → register_dv5shim_func`、`unregister_dv_functions → unregister_dv5shim_func`；
  配套内核模块 `dv_compat_shim`（cpm 分支新增）提供桩符号
  `get_cpu_type_from_media`、`__cfi_slowpath_diag`、`__ubsan_handle_cfi_check_fail_abort`、`__stack_chk_fail`，
  以及 `dv5_compat_abi.h` 的 `struct dv5_funcs` 适配层。
- 功能：FEL（CMv4.0、DV-LL、Chroma Weight 修复）、`DV Type` 切换（Display-Led DV-Std / Player-Led / "DV as VS10 Only"）、
  HDR10+ → DV CMv4.0 转换、VS10 转换、Video/OSD/字幕独立线程、字幕 DV L5 亮度模式、`CMv4.0 on the fly append`。
- **安装要求**：设备对应的 `dovi.ko` **和** `dovi5.ko` 两个模块（`dovi5.ko` 由 discourse 上传的 blob 现场生成）。
  → 再次依赖授权机型，**不适用于 GXL**。

### 3.2 CoreELEC 22.0-Piers（2026-06 beta）

- 变更说明："Add support for Dolby Vision FEL on all licensed SoCs except S5, S928X"；
  但同页写明 **"Devices using Amlogic SoC S905X (GXL) or older will no longer be supported by CoreELEC 22.0-Piers"**，
  内核升级到 5.15.196。
- 结论：官方路线已经在 N1 上终止；N1 的长期基线只能是 21.3 NG。

### 3.3 其他

- doppingkoala：`xbmc` 分支最新为 `public_dv_pov`(2026-02-23)；`common_drivers` 仅 `public_dv_poc`(2026-01-03)；
  2026-02-21 后公开活动停止，CE-NO 路线因性能搁置。
- 社区可用性共识：双层杜比需 `-J/-K` 机型 + CoreELEC **NG** 固件（21.x）；CE-NO(5.15) 当年缺 dovi.ko，
  后由 djnice77 在 2026 年补上。

---

## 4. N1 上的实施方案（三条轨道）

### 4.0 原理速览：三种 profile 在链路上到底差在哪

| Profile | 码流构成 | 电视需要什么才能正确显示 |
|---|---|---|
| **P8** | HDR10 兼容 **BL**（10bit YUV/BT.2020/PQ）+ **RPU**（H.265 NAL 62，含 L1/L2：DM 亮度曲线、色彩映射） | 收到 RPU 才有 DV；只收 BL 就是普通 HDR10（电视自己 tone map） |
| **P5** | 单层 **IPT-PQ**（杜比自有 IPT 色彩空间 + PQ），**无 RPU** | 像素不是 HDR10 兼容基线 → 电视直接播必然偏色；必须先做映射/转换 |
| **P7 MEL/FEL** | BL + **EL**（增强层，含完整 RPU） | 硬解合成 BL+EL（MEL 丢弃、FEL 合成），再走 DV 输出 |

所以"杜比视界播放"在三处发生：①码流层处理（RPU 剥离/转换/合成，Kodi + libdovi）②像素层转换（DV→HDR10 色调映射，
纯软件）③输出层（DV Core 把 RPU 塞进 HDMI VSIF，或授权 blob 在 TEE 里重塑像素）。
**只有 ③ 需要 DV Core 硬件 + 杜比授权**；① 和 ② 在 N1 上都能做。

### 轨道 A：基线内可立即用的能力（零移植，先做）

1. 基线已含 libdovi + Kodi 的 `videoplayer.convertdovi`（Kodi 内置"把 DV 转 HDR"）与
   `coreelec.amlogic.dovizerolevel5`（P5 处理）。先在基线固件上把设置项摸清并记录行为。
2. **已知缺口**：上游 21.3 的 `BitstreamConverter.h:123` 提供了 `SetRemoveDovi()`，但在 Kodi 的 Amlogic 相关文件里
   **没有任何调用点**（`m_removeDovi` 恒为 false，`BitstreamConverter.cpp:1099` 的 RPU 剥离分支永不命中）。
   cpm 分支在 `DVDVideoCodecAmlogic.cpp:632` 补上了 `m_bitstream->SetRemoveDovi(true)`（并配合 `SetRemoveHdr10Plus(true)`）。
   → 建议把这一处（含 HDR10+ 元数据剥离）作为**独立小补丁**回移，使 P8 在 N1 上干净地按 HDR10 显示。
3. 判据：以 MediaInfo 确认片源 profile，以电视端实际显示为 HDR10（非 DV 徽标）、黑位/亮度正常为准。

### 轨道 B：P5 的现实解法（软件 VS10 / 离线转换）

P5 = 单层 IPT-PQ，**没有 RPU**，底层不是 HDR10 兼容基线，所以"直接当 HDR10 播"会偏色/发灰。三条可行路径：

1. **在线软件色调映射（Kodi/GLES + libplacebo）**
   - 现状约束：本项目 `packages/addons/addon-depends/multimedia-tools-depends/libplacebo/package.mk`
     以 `-Ddovi=disabled -Dlibdovi=disabled` 构建，**没有 Dolby Vision 支持**。
   - 动作：重建 libplacebo 时打开 `-Ddovi=enabled -Dlibdovi=enabled`，并让 Kodi 的 GLES 渲染路径走 libplacebo
     （Kodi 侧 `videoplayer.convertdovi` 的实际实现需在 `acc0fc66` 源码里定位确认，见 §6 未决项）。
   - 性能预期：S905X 做 4K 软件 DV 色调映射不现实，**建议限定 1080p/720p**，4K 走离线。
2. **离线转码（推荐主力）**
   - `dovi_tool`（dovi_tool 3.3.1 已在本项目内）：P5 → 生成 RPU → P8（`-p 8`，`gen-rpu --profile 5`），
     再用 `ffmpeg + libplacebo` 做 VS10 色调映射输出 HDR10/SDR 文件；N1 只负责播放。
   - 也可只做 P5→P8 保留 DV 语义，交给电视做 DV-LL——**但前提是 GXL 能把 VSIF/RPU 送到电视**，
     而 GXL 的 HDMI TX 路径未经验证（`dv_emp_vsem.c` 属 DV core 体系），列为未决项。
3. **换机**：若确实要"原生杜比 + FEL"，硬件前提是 S905X4-J/K 或 S922X-J/K，配合 avdvplus R10（NG 21.3 + dovi.ko + dovi5.ko）。

### 轨道 C：为将来上授权硬件预留的补丁层（可选，与基线分离）

把 cpm/avdvplus 的 Kodi 侧 DV 能力做成**可开关的独立补丁层**，与 21.3 基线分离：

- 设置集：`DV Type`（Display-Led DV-Std / Player-Led / VS10 Only）、`Video Processor`、
  `CMv4.0 append`（含 Auto/Auto2 阈值）、`VS10` 相关、`DV STD source level 5`（P5 + OSDST）、
  字幕 `DV L5 signal mode`、`VSVDB max lum`。
- 内核/打包侧（仅在授权 SoC 才有意义）：`dv_compat_shim`、`dovi5-prepare`（`dv5-patch-dovi.py`）、
  `dovi-loader.sh` 增加 dovi5 装载与 stamp 校验。
- **在 GXL 上这些补丁不会产生原生 DV 输出**（`chip_support_dv()` 门槛），只影响 Kodi 侧的码流处理与 VS10 路径。

---

## 5. 输出段能否绕行：源码级结论 + 自研播放器的原理

结论：**能绕，而且不需要杜比授权、不需要 DV Core。** 关键是 doppingkoala 2024 年在 OSMC 公开的
"TV-led DV on any device" 原理（§5.0），以及我们基线内核里**已经存在**的 TV-led 接口（§5.1–§5.3）。

### 5.0 自研播放器的 TV-led DV 原理（doppingkoala, OSMC 2024-05-18 ~ 06-28）

[OSMC 论坛 "Support for TV-led Dolby Vision on all devices"](https://discourse.osmc.tv/t/support-for-tv-led-dolby-vision-on-all-devices/107473)
作者的原始表述：

> "all that is needed to do to enable tv-led dolby vision is to **embed the metadata in the top pixels of the
> 12-bit 422 signal** that is outputted from the device and send the correct **hdmi vendor-specific infoframe
> and avi packet** (these are known). The metadata to embed in these pixels can be easily formed from the
> metadata that the **dovi_tool** extracts. The major problem I am stuck on is **how to embed the required data
> into the top pixels that are actually output**."

- 关键点：**盒子不做像素重塑**，只把 RPU 派生的 L1/L2 元数据**写进 12bit 4:2:2 输出的顶部像素**，
  再发 Dolby VSIF + AVI InfoFrame；**电视（DV 显示器）从顶部像素取出元数据并完成重塑**。
- 因此这条路线**不需要 DV Core、不需要 dovi.ko、不需要杜比授权**——这正是"非授权设备也能出真 DV"的原因。
- 作者的实测记录（同一线程）：
  - 8bit：`double_write_mode=1` 时解码缓冲是 NV21 格式，可读可写 → **能实时内嵌并得到电视的 DV 响应**，
    但只支持 16:9（元数据必须放进实际传输的顶部像素），且强制 8bit 输出；
  - 10bit：解码缓冲是"compressed and scattered"格式，难以逐像素改写；
  - 2024-06-19 "It's alive!!! - DV working for non licensed devices"：能从播放中的文件实时读出元数据并使用（先只有 L1）；
  - 2024-06-28：**cmv2.9 / cmv4.0 全等级元数据可用**，并附带 level 5 元数据
    （"the level 5 metadata that doesn't appear to be used by other players in tv-led mode. Sending the level 5
    data avoids the problems with L2 positive lift"）——**level 5 正是 P5 的标记**。
- 由此推出 **P5 也能走 TV-led**：P5 本身没有 RPU，需要先用 dovi_tool 合成一份 RPU
  （`dovi_tool gen-rpu --profile 5`），再按同样方式内嵌其 L1/L2/level5 元数据 → 电视完成重塑。
  这也解释了作者 2025-12 的 "P5 实验版"为什么能加 profile 5 支持。
- 相关上游痕迹：`CoreELEC/linux-amlogic` 提交 `35abaaa`（2024-04-22，"Add parameter to control clearing of
  colorimetry flag for tv-led dovi"）修改 `hdmi_tx_main.c` / `hdmi_tx_hw.c`，**该提交已在我们锁定的 4.9 基线里**。

**完整实现清单（作者在 CoreELEC 50998 #211 起陆续公开）**

一次性设置：Kodi → **12-bit 4:2:2**、GUI 分辨率 **3840x2160**、开启 "**Disable GUI scaling**" → 重启。

运行时内核参数（4.9/NG 路径）：

| 参数 | 模块 | 作用 |
|---|---|---|
| `inject_osd_metadata` | `amvideo` | 把元数据注入 **OSD/GUI 层**顶部像素 |
| `metadata_buffer` / `metadata_buffer2` | `amvideo` | 两套 L1/L2 元数据字节，可轮换 |
| `random_data_count` + `toggle_metadata_count_limit` | `amvideo` | 每 N 帧轮换两套元数据（作者称"亮度按此切换"） |
| `metadata_toggle` | `amvideo` | 手动轮换 |
| `DV_vsif_send_in_hdmi_packet` | `am_vecm`（CE22 为 `aml_media`） | 在 HDMI 包里发送 Dolby VSIF |
| `DV_enable` / `DV_disable_vsif` | `/sys/devices/virtual/...` | 开关 DV 指示 |

作者结论：**"This build should provide tv-led DV from any device (licenced or not)"**，且
**"for profile 5 content, correct colors being displayed (when using the default metadata)"**。

已知坑（作者与测试者反馈）：仅支持 16:9（元数据随顶部像素走）；要求 3840x2160 + 12bit 422 GUI；
暂停/按信息键会黑屏；停止播放后可能黑屏需 `DV_disable_vsif` 或重启；DV 模式下字幕卡顿；
10bit 需试参数。2024-07-13 作者重写并迁移到 CE22 + 5.15（302MB），2024-08 又提供 20.5/4.9 可用版本。

**已发布的测试镜像清单（可直接取用）**

| 时间/版本 | 链接 | 说明 |
|---|---|---|
| 2024-04-20 | `mega.nz/file/cdhX3YST#HexKZShkzfO7FxTdd5W0bOIlUnwW1a6cy16qCgIZVEs` | 早期 RGB full-range 试验版 |
| 2024-06-12 | `mega.nz/file/sQwFVJ7J#oCc_vwU1JaRQgAAnP5QOYXrh7h63Zsy8QhpGP8WWAnU` | 4.9/NG，10bit 试验 |
| 2024-06-09（#211） | `mega.nz/file/cJpzGYzI#B0ZbBJTQ3PEa53puTEcoEcwg5VD5DdQo_k2K_khs4K0`（248.11 MB） | **首次"成功内嵌元数据"**，GUI 层方案 |
| 2024-06/07 | `mega.nz/file/tYon3BjI#CH_7f-vLkL8hQ0SOK6_P-ZJImz-enFkpohFovgrs3-k`（248.02 MB） | 4.9/NG 完善版 |
| 2024-07-13（#282） | `mega.nz/file/kZYCVaYB#KpbLjyNUEs5O85md_DjXbWZ7ztQLga26ncpIUnlZVa8`（302.44 MB） | 重写并迁移到 **CE22 + 5.15** |
| 更晚 | `mega.nz/file/8Fgh0Swb#6OC_QkRO-MfpK2OfO4V0Mp3UjhTUzHFRh4ActhH8jMM`（312.91 MB） | — |
| 2025-12（57985 #1） | `mega.nz/file/wJAmAa6S#rZbqLQJxzSgvE03nIaRtVjWj_325ZLZR9vhnVEGSBnA`（260.81 MB） | **P5 版**，21.1 基线 |
| 元数据/素材 | `mega.nz/file/0BgwhRgK#3oHMgtq-6y-ko6A1a3Wth6A0E1LT_ttT3SMAckjgktg`（2.29 MB）、`kE4h3Tab#...`（13 MB）、`IdIQASCD#...`（4.39 MB） | 元数据字节与测试素材 |

配套资料：
- 5.15 版元数据注入实现：`doppingkoala/common_drivers @ eb85e7bd` → `drivers/media/video_sink/dv_injection.c`（见 §2.2）
- 4.9 canvas（GUI 层写入点）：`CoreELEC/linux-amlogic @ amlogic-4.9-20` → `drivers/amlogic/media/common/canvas/canvas.c`
- **TV-led DM 元数据生成**：`quietvoid/dovi_tool` issue #303（"Add feature to write display management metadata suited for tv-led DV"）——
  工具侧已具备输出 TV-led DM 的能力，配合基线已有的 libdovi 3.3.1
- 另一位实现者：OSMC "[TESTING] Vero V: Dolby Vision TV led support"（djnice）

**我们基线的差距（已核）**：`linux-amlogic @50c8e815` 的 `video_sink.c`（模块 `amvideo`）里
**没有** `inject_osd_metadata` / `metadata_buffer` / `random_data_count` / `toggle_metadata_count_limit` /
`metadata_toggle`；`am_vecm.c` 里也**没有** `DV_vsif_send_in_hdmi_packet`。
→ 这套 TV-led 能力**不是上游**，是作者自己的内核补丁，需要移植。

### 5.1 注入 API 属于 HDMI TX，不属于 DV Core

`drivers/amlogic/media/vout/hdmitx/hdmi_tx_20/dv_emp_vsem.c`（4.9 树）：

```c
int send_emp(enum eotf_type type, enum mode_type tunnel_mode,
             struct dv_vsif_para *vsif_data,
             unsigned char *p_vsem, int vsem_len, bool signal_sdr);
EXPORT_SYMBOL(send_emp);            // 第 469 行
```

- `dv_emp_vsem.o` **无条件编入** `hdmitx20.ko`（`hdmi_tx_20/Makefile`），因此在 GXL 上这个模块存在。
- 它的芯片门槛是"下界制"，把 GXL 正好放进来的：

```c
if ((hdev->chip_type) < MESON_CPU_ID_GXL) {
        pr_info("EMP hdmitx: not support DolbyVision\n");
        return -1;
}
if ((hdev->ready == 0) || (hdev->rxcap.dv_info.ieeeoui != DV_IEEE_OUI))
        return -1;
```

  - 第一道：`chip_type >= MESON_CPU_ID_GXL` → **N1 达标**（对比 `amdolby_vision.c` 的 `chip_support_dv()` 是白名单制，GXL 不在其中）。
  - 第二道：**电视**必须在 EDID/VSVDB 里声明杜比视界（`DV_IEEE_OUI`）；需从实际连接读取确认。

### 5.2 GXL 上的第二条注入路径：HDMI 1.4b Vendor Specific InfoFrame

`hdmi_tx_main.c` 的 `hdmitx_set_vsif_pkt()`（经 `vout_device->fresh_tx_vsif_pkt` 暴露）：

```c
if ((hdev->chip_type) < MESON_CPU_ID_GXL) { pr_info("hdmitx: not support DolbyVision\n"); return; }
...
if ((hdev->rxcap.dv_info.ver == 0) ||
    ((hdev->rxcap.dv_info.ver == 1) && (hdev->rxcap.dv_info.length == 0xE)) ||
    ((hdev->rxcap.dv_info.ver == 1) && (hdev->rxcap.dv_info.length == 0xB) &&
     (hdev->rxcap.dv_info.low_latency == 0))) {
        /* ver0 / ver1_15 / ver1_12bit(ll=0) → 用 HDMI 1.4b VSIF */
        len = 0x18;  hdev->dv_src_feature = 1;   /* EOTF_T_DOLBYVISION */
        VEN_DB1[0] = 0x03; VEN_DB1[1] = 0x0c;     /* IEEE OUI 0x000C03 = Dolby */
        hdev->hwop.setpacket(HDMI_PACKET_VEND, VEN_DB1, VEN_HB);
}
```

- 门槛同样是 **`chip_type < MESON_CPU_ID_GXL` 才拒绝** → GXL 通过。
- 这条路发的是标准 **HDMI Vendor Specific InfoFrame**（1.4b VSIF，24 字节 Dolby "DV Video Signaling"），
  与 `send_emp()` 的 EMP/VSEM 路径并存；用哪条取决于**电视在 EDID 里申报的 DV 版本**
  （`rxcap.dv_info.ver / .length / .low_latency`）。
- 结论：**"元数据怎么送出去"在 GXL 上有两条现成实现，都不需要杜比授权**；缺的只是把 RPU 喂进去的那一环。

### 5.3 DV Core 只是 `send_emp()` 的调用者

`amdolby_vision.c` 里的两种用法：

- 隧道模式：`send_emp(EOTF_T_DOLBYVISION, tunnel ? RGB_8BIT : YUV422_BIT12, NULL, hdmi_metadata, hdmi_metadata_size, false)`
  → `vsif_data = NULL`，payload 就是**整段 RPU**。
- DV-LL 模式：`send_emp(EOTF_T_LL_MODE, RGB_10_12BIT | YUV422_BIT12, &vsif, vsif_emp, 15, false)`
  → 15 字节 VSEM + VSIF 结构体，由 `prepare_vsif_pkt()` / `prepare_emp_vsif_pkt()` 从 `dovi_setting` 生成
  （这两个是 `amdolby_vision.c` 内的 static 函数，需要移植或重写）。

→ 我们要做的是**自己成为调用者**，而不是"打开 DV Core"。`send_emp` 是导出符号，任何内核模块都能调。

### 5.4 绕行方案（工作项，按 §5.0 原理）

1. **元数据拿到手**：Kodi 侧用 libdovi（dovi_tool 3.3.1，基线已有）：
   - P8/P7：取 RPU 的 L1/L2（`processDoviRpu()` 已在基线里做 `dovi_parse_unspec62_nalu`）；
   - P5：**合成** RPU（`gen-rpu --profile 5` 级别）→ 得到可用的 L1/L2/level5。
   经新增 ioctl/sysfs 把元数据交给内核。
2. **顶部像素内嵌（核心工作量）**：在 4.9 树的输出路径上，于帧送到显示缓冲前把元数据写进顶部行。
   作者给的形态是 `phys_to_virt(dispbuf->canvas0_config[0].phy_addr)` 后逐字节写入
   （依赖解码器 `double_write_mode=1` 提供的可写 NV21 缓冲，8bit 可行；10bit 需另找写入点）。
3. **VSIF + AVI InfoFrame**：基线内核**已有** TV-led 分支与参数：
   `hdmi_tx_main.c` 的 `hdmitx_set_vsif_pkt()` TV-led 分支（VSIF OUI `0x000C03`、24 字节 DV Video Signaling）、
   `dovi_tv_led_bt2020` / `dovi_tv_led_no_colorimetry`（模块参数）、`SET_AVI_NO_CM`（清 AVI colorimetry 标志）、
   `hdmitx_dv_en()`。→ 这部分**基本不用写代码**，只需在 Kodi 侧驱动这些参数。
4. **输出格式**：DV over HDMI 常规要求 **12bit 4:2:2**（`send_emp` 的 `YUV422_BIT12`）；
   需实测 GXL HDMI TX 在 1080p60 / 4K60 下能否输出 12bit 4:2:2。
5. **抑制冲突 InfoFrame**：避免普通 HDR10 VSIF/InfoFrame 与 DV 指示冲突
   （4.9 对应 `drivers/amlogic/media/enhancement/amvecm/amcsc_pip.c` 的 `hdmi_packet_process()` 分支）。

### 5.5 仍然绕不过去的边界（诚实说明）

- **Player-led（盒子自己重塑）不可行**：重塑是杜比 IP（DV Core + 授权 blob），N1 两样都没有。
- **FEL 不可行**：FEL 需要 BL+EL 合成后的重塑（同样要授权 blob）；只能退化为 BL + HDR10。
- **P5 必须先合成 RPU**：P5 无 RPU，若要走 TV-led 真 DV，需 dovi_tool 合成 RPU 再内嵌其元数据；
  不想做这一步就只能走软件 VS10（P5→HDR10）。
- **顶部像素写入的可行性是硬门槛**：10bit 流的解码缓冲是压缩/分散格式，作者当年也卡在这里；
  8bit 路径可行但强制 8bit 输出。→ 决定 N1 能做到什么画质档位。

### 5.6 未知 / 风险

- **顶部像素写入点**：4.9 树里到底在哪个环节能拿到"可写的 12bit 4:2:2 顶部行"（解码器 double_write 缓冲？
  VPP 输出前？），是本路线最大的实现风险。
- **GXL 的 12bit 4:2:2 能力**：1080p60 应无问题；4K60 12bit 4:2:2 需实测。
- **电视端接受条件**：显示设备需能识别顶部像素里的 DV 元数据（不同 TV 差异大），并配合 VSIF/AVI。
- 作者的实现**未开源**（"Not yet on github"），需按原理自行实现或参考其帖中给出的注入代码片段。
- 成本结构：**不是配置开关，是研究级工程**（元数据提取/合成 + 内嵌写入 + 参数编排 + 实机验证）。

---

## 6. 验收与证据要求（对齐 `docs/n1-acceptance.md` 第 6 条）

1. 先取证：MediaInfo 的 DV profile / level / EL 类型；`cat /sys/class/drm/card0-HDMI-A-1/edid`；
   `/sys/class/amdolby_vision/support_info`（N1 上应不存在或为 0）；Kodi 系统信息里的显示能力。
2. 在本地确认显示能力（以 EDID/dv_cap 为准）；不公开个人设备资料。
3. 分开测试：P8（应得 HDR10）、P5（应得 HDR10 且色彩正常）、P7 MEL（应得 HDR10）。
4. 对比项：黑位/裁剪、字幕与 OSD、seek、A/V sync；**DV 徽标不能作为重塑正确的证据**。
5. CI 与实机检查分开记账；本轮仍不得宣称"DV 播放已验证"。

---

## 7. 未决项 / 需要下一步确认

- `videoplayer.convertdovi` 在 `acc0fc66` 中的实际实现位置与依赖（是否必须 libplacebo 的 dovi 支持）。
- GXL 的 HDMI TX 是否存在可用的独立 VSIF/EMP 注入路径（绕过 DV core），从而让 P8+P5-RPU 以 DV-LL 送给电视。
- CoreELEC 21.3 官方 wiki 的 DV 支持机型清单（wiki 页面当前对未登录用户 ACL 拒绝，需换渠道核对）。
- N1 原厂 Android 固件中是否确实不含 `dovi.ko`（若有，可省去换机成本，但 `chip_support_dv()` 仍会拦截）。
- avdvplus R10 的 `dovi5.ko` 上传链接与 `dv5-patch-dovi.py` 对不同 kernel vermagic 的适配范围。

---

## 8. 引用

- [CoreELEC 论坛：Dolby Vision for all SoCs（57985）](https://discourse.coreelec.org/t/dolby-vision-for-all-socs/57985)
- [CoreELEC 论坛：Learning about Dolby Vision and CoreELEC development（50998）](https://discourse.coreelec.org/t/learning-about-dolby-vision-and-coreelec-development/50998)
- [OSMC 论坛：Support for TV-led Dolby Vision on all devices（107473，doppingkoala 公开原理与实现进展）](https://discourse.osmc.tv/t/support-for-tv-led-dolby-vision-on-all-devices/107473)
- [CoreELEC/linux-amlogic 提交 35abaaa（tv-led dovi colorimetry 参数，已在基线内核中）](https://github.com/CoreELEC/linux-amlogic/commit/35abaaa771e177c95d1b8e418792f4010c094e46)
- [avdvplus/Builds R10 发布说明（2026-09-06）](https://github.com/avdvplus/Builds/releases/tag/avdvplus_R10)
- [CoreELEC 22.0-Piers beta1 变更说明](https://newreleases.io/project/github/CoreELEC/CoreELEC/release/22.0-Piers_beta1)
- [CoreELEC 官网（CE22 放弃 GXL 的说明）](https://coreelec.org/)
- [avdvplus/CoreELEC（coreelec-21-cpm）dovi5-prepare 包](https://github.com/avdvplus/CoreELEC)
- [doppingkoala/xbmc](https://github.com/doppingkoala/xbmc)、[doppingkoala/common_drivers](https://github.com/doppingkoala/common_drivers)
- [社区机型授权说明（-J/-K 才具备杜比双层硬件）](http://mp.weixin.qq.com/s?__biz=Mzg4NzA5OTY1Mg==&mid=2247484422&idx=1&sn=64ecfd6ee1b434a76f79afa6d3094e57)
- [CoreELEC 杜比视界驱动安装说明（机型清单）](http://www.kodiplayer.cn/coreelec/course-coreelec/3096.html)

---

## §9 从已发布构建反推的实现规格（2026-10-27 取证）

> 本节结论全部来自**实际下载并拆解的已发布构建**，不是推断。

### 9.1 取到的产物

| 产物 | 标识 | 大小 | SHA-256 |
|---|---|---|---|
| **P5 构建（21.1 NG / 4.9.269）** | `CoreELEC-Amlogic-ng.arm-21.1.1-Omega_devel_20251214200924.tar`（MEGA `wJAmAa6S`） | 273,479,680 | `879d4026…8a4e4a7` |
| CE-NO 构建（22.0 / 5.15） | `CoreELEC-Amlogic-no.aarch64-22.0-P_devel_20240821184405.tar`（MEGA `8Fgh0Swb`） | 328,110,080 | — |
| P5 构建的 Kodi | commit **`d4ee2ad4`**（= `doppingkoala/xbmc` 分支 `aml-4.9-21.2` 头） | — | — |
| **公开实现源码** | `doppingkoala/common_drivers@eb85e7bd` → `drivers/media/video_sink/dv_injection.c` | 372,880 | `93d0077e…ac29556` |

其余 MEGA 链接（`tYon3BjI`/`kZYCVaYB`/`sQwFVJ7J`/`cdhX3YST` 等）**已被删除**（API 返回 -9）；
`2J8HRZBK` 实为 DV 测试样片 `24.00Hz.DV.P7.FEL.sample.mkv`，`IdIQASCD` 为 `glassblowing_frame.mkv`。

拆包方法：`target/KERNEL` 是 ANDROID! bootimg（kernel_size 字段在偏移 8），内核载荷是 **lzop**
（magic `\x89LZO\x00\r\n\x1a\n`）压缩，需按 lzop 容器解析（method 3 = LZO1X，
块头 8 字节 BE + 4 字节 CRC）后得 28,184,584 字节 arm64 Image。

### 9.2 内核侧 delta：我们的 4.9 基线 vs 他的 P5 内核

对 P5 内核做全量字符串提取，与我们基线 `linux-amlogic@50c8e815` 的 123 个 media 源文件
逐条比对，**新增且仅新增在 `amvideo`（`drivers/amlogic/media/video_sink/video.c`）**：

| 新增模块参数 | 作用 |
|---|---|
| `amvideo.inject_osd_metadata` | **总开关**：把 DV 元数据注入 OSD/GUI 层顶部像素 |
| `amvideo.osd_canvas` | 目标 canvas 索引 |
| `amvideo.osd_L5_timeout_ms` | L5 生效超时 |
| `amvideo.always_send_vsif` | 每次都发 VSIF（不等内容变化） |
| `amvideo.auto_block_other_vsif_for_DV` | 有 DV 元数据时屏蔽其它 VSIF |
| `amvideo.force_block_other_vsif_for_DV` | 强制屏蔽 |
| `amvideo.generate_DV_from_hdr10p` | **HDR10+ → DV** 合成 |
| `amvideo.hdr10plus_convert_method` | 转换算法：`PQ CDF` / `original dovi_tool method` |
| `amvideo.omx_pts_dv_lower/upper` | DV 帧的 PTS 窗口 |
| `amvideo.disable_dv_drop` / `clip_hdr10plus_pq` | 丢帧与 PQ 裁剪 |

新增实现字符串（同为 `amvideo`）：
`Getting canvas pointer`、`Getting vdr_dm_metadata pointer and size`、`Using embedded dv metadata`、
`Modify L1 vdr_dm_metadata`、`Modify L5 vdr_dm_metadata`、`Modify full_range_flag in vdr_dm_metadata`、
`L1.min_pq adjusted to source_min_pq`、`L1.max_pq adjusted to source_max_pq`、
`Checking if L5 adjustment needed for metadata`、`Sending vsif + setting avi packet`、
`Creating DV metadata from HDR10+ data`、`Converting HDR10+ using PQ CDF`、
`Converting HDR10+ using original dovi_tool method`、`Found DV data in sei`、`Found HDR10+ data in sei`、
`DV frame needs reshaping`、`Not a DV frame. fmt is: %d`；
边界：`DOLBY ERROR: rpu exceed 512 bytes`、`core3 metadata size %d > 204 !`、`vsif size = %d`。

**基线已具备、无需移植的部分**（此前判断有误，此处更正）：`prepare_vsif_pkt()`、
`prepare_emp_vsif_pkt()`、`vsem_if_buf`、`register_dv_tv_functions`、`register_dv_stb_functions`、
HDR10+ 处理、IPT/tunnel 模式 —— 全部在 `amdolby_vision.c` 里（88 处 VSIF 命中）。
`hdmitx20.dovi_tv_led_bt2020` / `dovi_tv_led_no_colorimetry` 亦已在基线（提交 `35abaaa`，已核为 `50c8e815` 祖先）。
**结论：缺口只在 `amvideo` 一个模块。**

### 9.3 算法还原（公开源码 `dv_injection.c`）

1. 取 RPU 中的 **DM（Display Management）元数据**（≤594 B；core3 ≤204 B）。
2. **分包**：每包 128 B，头部 `b0 ∈ {0x00 单包, 0x40 首包, 0x80 中间包, 0xC0 末包}`、
   `b1 = dm[0]`、`b2 = 0`、`b3b4 = 总长度(BE)`；首包正文 119 B，后续包 121 B；
   末尾 4 B 为 **CRC32（偏移 124，大端写入）**，计算范围为前 124 B；最多 5 包。
3. **位→像素编码**：每个字节的每个 bit 变成一个 32-bit 像素，bit=1 → `0xFFFFFFFF`，
   bit=0 → `0xFF000000`（128 B → 1024 像素）。
4. **写入**：目标 buffer = **OSD canvas**（`canvas_read(osd_canvas, &cs0)` → `phys_to_virt(cs0.addr)`），
   写在左上角，页偏移 `page * osd_pixel_offset`（4K 用 4 行），每包重复 3 次。
5. **发 VSIF**：`vinfo->vout_device->fresh_tx_vsif_pkt(EOTF_T_DOLBYVISION, RGB_8BIT, &vsif_para, 0)`，
   `vsif_para.vers.ver2.dobly_vision_signal = 1`（DV STD）。
6. **L1/L5 修正**：`auto_set_L1()` 把 L1 的 min_pq/max_pq 夹到 source_min_pq/source_max_pq；
   `auto_set_L5()` 按屏幕尺寸修正 active area。
7. **HDR10+ → DV**：`form_dv_sei_payload_from_hdr10plus()` 用 PQ CDF（或 dovi_tool 法）生成
   117 B 的 DV SEI 载荷，再走同一条注入路径。
8. `should_block_vsif()` → 有 DV 元数据时屏蔽其它 VSIF，避免与普通 HDR10+ VSIF 冲突。

### 9.4 我们 4.9 基线的 API 可用性核对（逐项已验证）

| 依赖 | 4.9 基线 | 位置 |
|---|---|---|
| `canvas_read(canvas_idx, &cs)` | ✅ 存在 | `video_keeper.c:154` 等 11 处 |
| `fresh_tx_vsif_pkt` | ✅ 存在 | `amdolby_vision.c:7309` |
| `update_vframe_src_fmt(vf, sei, size, dual_layer, …)` | ✅ 存在，且**已收到 SEI 载荷** | `video.c:7663` |
| `check_media_sei(sei, size, DV_SEI/HDR10P)` | ✅ 已有 DV_SEI=0x01000000 / HDR10P=0x02000000 解析 | `video.c:7571` |
| `VFRAME_SIGNAL_FMT_DOVI` | ✅ 存在 | `amdolby_vision.c:5803` |
| `vf->prop.master_display_colour` | ✅ 存在 | `amcsc_pip.c` |
| `vdr_dm_metadata`（5.15 的 vframe 字段） | ❌ 没有 → **改从 SEI 直接取 DM**（`dv_injection.c` 本来就这么做） |
| `hdmitx_set_vsif_pkt`（5.15 命名） | ❌ 无 → 用 4.9 的 `fresh_tx_vsif_pkt` |

### 9.5 N1 实施步骤（文件级）

1. **内核**：把 `dv_injection.c`（372 KB，自包含）移植到 `drivers/amlogic/media/video_sink/`，
   并入 `amvideo`（`video.c`）模块；改 4 处 API：`canvas_read` 调用点、`fresh_tx_vsif_pkt`、
   `vdr_dm_data_source` 改为 SEI 直取、`osd_pixel_offset`/`repeats_to_write` 改为 4.9 的 canvas 布局。
   新增上述 11 个 `module_param`。
2. **钩子**：`update_vframe_src_fmt()` 末尾调用 `update_dv_hdr_dm_pkt(sei, size, vf)`；
   在 OSD/GUI 层渲染路径（canvas 提交前）调用 `dv_metadata_injection(vf)`。
3. **Kodi**：从 `doppingkoala/xbmc` 分支 `aml-4.9-21.2`（head `d4ee2ad4`）取 DV 相关提交：
   `619ad830`（P5→HDR10/SDR 转换）、`264b2d31`（自动隐藏 Disable GUI scaling）、
   `8f6c2bfd`（渲染缓冲尺寸与内核匹配）、`7b579103`/`55a6b7bf`/`37d4ef63`（BL+EL 合并与转发）、
   `6094fab6`（无 DV 屏时隐藏 DV 选项）、`88def351`/`4d89a776`（EL 层 PID、双流等待 BL）、
   `ee76c95b`（仅 DV 屏强制切模式）、`6c395118`（GUI 峰值亮度）。
4. **运行配置**：Kodi 12-bit 4:2:2 + GUI 3840×2160 + "Disable GUI scaling"；
   `echo Y > /sys/module/amvideo/parameters/inject_osd_metadata`。
5. **前置条件**：目标电视必须支持 TV-led DV（读 EDID `rxcap.dv_info` 确认）、
   GXL 的 HDMI TX 能发 EMP/VSIF、12-bit 4:2:2 @4K 可用。

### 9.6 风险

- 他的 **4.9 内核补丁本身未公开**（`doppingkoala/CoreELEC` fork 只有 `coreelec-22` 分支，
  `common_drivers` 的 4.9 分支里没有 DV 文件）→ 我们是**按公开的 5.15 实现重写**，不是复制。
- 4.9 的 canvas 与 5.15 的 frame 布局不同，**顶部像素位置需实测标定**（`osd_pixel_offset`）。
- 4K 时 RPU 长度上限：内核报 `rpu exceed 512 bytes`、`core3 metadata size > 204`。
- GUI 层方案对 Kodi 缩放/皮肤敏感（作者本人因此在 5.15 改回视频帧注入）。

---

## §10 已实现的成品清单与借鉴方案（2026-10-27 检索）

| # | 成品 | 基线 | 机制 | 源码公开 | 对 N1 的适用性 |
|---|---|---|---|---|---|
| A | **doppingkoala `public_dv_poc`**（2026-01-03，"working dv overlay"） | 5.15 `common_drivers` | 100 行 `dv_injection.c` 骨架 + 新增 DRM plane + `meson_hdmi.c` 强制 YUV422 + `amcsc_pip.c` 抑制冲突 InfoFrame | ✅ 全公开 patch | ★★☆ 最小原型，但走 **DRM plane + 已内嵌元数据** 假设，4.9 无对应 plane |
| B | **doppingkoala `dv_injection.c`**（`eb85e7bd`，372 KB） | 5.15 `common_drivers` | 完整实现：DM 分包 / CRC32 / bit→像素 / canvas 注入 / L1·L5 修正 / HDR10+→DV | ✅ 全公开 | ★★★ **算法全文**，直接移植到 4.9 |
| C | **doppingkoala P5 build**（2025-12，21.1 NG / 4.9.269） | **4.9（与我们同代）** | `amvideo` 新增 11 参数 + OSD/canvas 顶部像素注入 + VSIF | 镜像公开，内核补丁私有 | ★★★ 4.9 集成点的实测依据（已拆解） |
| D | **doppingkoala `aml-4.9-21.2`**（Kodi） | Kodi 21.2 | P5→HDR10/SDR、GUI 缩放开关、BL+EL 合并转发 | ✅ 全公开 | ★★☆ Kodi 侧成品提交 |
| E | **avdvplus R10**（2026-09-06） | **21.3 NG（与我们完全同代）** | Player-led + `dovi5-prepare`(blob 改 vermagic) + `dv_compat_shim`；**并显式移除 TV 路径**（`remove p_funcs_tv` / `remove support for TV Soc` / `remove emp_vsif code`）；但保留 **VSVDB 注入** | ✅ 四个仓库全公开，198 提交 | ★★☆ 定位是授权 SoC（S905X4 等），**GXL 无 DV Core 不可用**；仅 VSVDB 注入思路可借 |
| F | **OSMC**（2026-03 Vero V TV-led，2026-05 FEL） | 5.15 / 6.12 | TV-led | 部分 | 参考 |
| G | **ZNDS 报道**（2024-08-06） | — | "coreelec 已实现无杜比授权播放杜比视界…支持 s905x2 那代开始" | — | 社区口径：s905x2+ 与 s905l3a 可用 → **N1（S905D/GXL）正面信号** |

### 10.1 关键结论：两条"成品"路线各有取舍

- **E（avdvplus）走 Player-led**：靠官方 `dovi.ko`/`dovi5` blob + shim，**需要硅片里的 DV Core** → GXL 没有 → N1 不可用。
  但它的 `inject_dolby_vsvdb()`（50 行，提交 `9ba28b33`）用的是**基线已有**的
  `dolby_vision_update_vsvdb_config()`（`amdolby_vision.c:1711`），**这一段可以几乎原样抄进我们的 4.9**。
- **A/B/C（doppingkoala）走 TV-led**：不需要 DV Core，**GXL 可用**；代价是内核补丁私有，
  但**算法本体（372 KB `dv_injection.c`）是公开的**，且 4.9 的集成点我们已从 P5 内核实测还原。

### 10.2 基线里"已现成可用"的注入原语（逐条已核）

| 原语 | 位置 | 是否被 DV Core 门控 |
|---|---|---|
| `hdmitx_set_vsif_pkt()` / `vinfo->vout_device->fresh_tx_vsif_pkt` | `hdmi_tx_main.c:1863` / `:118` | ❌ 不门控 → GXL 可用 |
| `dovi_tv_led_bt2020`、`dovi_tv_led_no_colorimetry` | `hdmi_tx_main.c:108-109` | ❌ 不门控（上游 TV-led 旋钮） |
| `dolby_vision_update_vsvdb_config(char*, u32)` | `amdolby_vision.c:1711` | ❌ 不门控 → **avdvplus 注入 VSDB 用的就是它** |
| `prepare_vsif_pkt()` / `prepare_emp_vsif_pkt()` | `amdolby_vision.c:7020` / `:7077` | ❌ 不门控 |
| `register_dv_tv_functions` / `register_dv_stb_functions` | `amdolby_vision.c` | ✅ `chip_support_dv()` 只门控 `register_dv_functions()`（:12034）→ GXL 只跳过 DV Core 注册 |
| `canvas_read()` | `video_keeper.c:154` 等 | ❌ 不门控 |
| `update_vframe_src_fmt(vf, sei, size, …)`（**已收 SEI**） | `video.c:7663` | ❌ 不门控 |
| `check_media_sei()` 已识别 `DV_SEI`/`HDR10P` | `video.c:7571` | ❌ 不门控 |

→ **除"像素注入 + L1/L5 修正 + 触发编排"外，其余在基线里全部现成。**

### 10.3 借鉴方案（推荐路径）

1. 抄 **B 的 `dv_injection.c`** 到 4.9 的 `drivers/amlogic/media/video_sink/`（路径改写），
   砍掉 5.15 专属：`vf->vdr_dm_metadata`（改为从 `update_vframe_src_fmt` 的 `sei` 直取）、
   DRM plane 依赖、`osd_pixel_offset` 的 5.15 取值（改为 4.9 canvas 布局，**需实测标定**）。
2. 抄 **E 的 `inject_dolby_vsvdb()`**（50 行）作为**补充**的 HDMI 层元数据通道：
   `dolby_vision_update_vsvdb_config("EB0146D000"+payload, 12)`。
3. Kodi 侧取 **D 的提交**（`619ad830`/`264b2d31`/`8f6c2bfd`/`7b579103`/`55a6b7bf`/`37d4ef63`…）。
4. 运行参数：`inject_osd_metadata=1`、Kodi 12-bit 4:2:2 + GUI 3840×2160 + Disable GUI scaling。

---

## §11 实施状态（2026-10-27 已入库）

用户授权后，TV-led 移植已落入本仓库：

| 内容 | 位置 |
|---|---|
| 内核补丁（5 文件 +512 行） | `projects/Amlogic-ce/devices/Amlogic-ng/patches/linux/linux-20-tv-led-dolby-vision-injection.patch` |
| 内核配置 | `projects/Amlogic-ce/devices/Amlogic-ng/linux/linux.aarch64.conf` → `CONFIG_AMLOGIC_MEDIA_VIDEO_DV_INJECTION=y` |
| 实施说明（参数、启用步骤、待标定项） | `docs/n1-dolby-vision-tv-led-port.md` |

补丁内容：新增 `dv_injection.c`（DM 分包 + CRC32 + bit→像素 → 写 OSD canvas → 发 VSIF）、
新增头文件、改 `video.c`（在 `update_vframe_src_fmt()` 里挂钩）、`Makefile`、`Kconfig`。
已用 `git apply --check` 对干净的 `linux-amlogic@amlogic-4.9-20` 树验证可应用。

**状态：已入库、内核编译通过（2026-10-27）、未上机。**
CI `kernel` 目标 exit 0：日志含 `CC drivers/amlogic/media/video_sink/dv_injection.o` 与
`LD drivers/amlogic/media/video_sink/amvideo.o`，无 error。
（整镜像构建随后另跑；期间修复了 CI 缓存问题，见下。）

**CI 环境的坑（已修）**：host 工具用 `-march=native` 编译，跨 CPU 家族恢复的 ccache 会
产出带本机不支持指令的二进制，导致 `bison: Illegal instruction`、`tar: Child died with
signal 4` 这类与补丁无关的失败。已把编译缓存键加上 CPU 指纹，源码缓存单独保存。

**整机镜像已构建**（CI run `40557456110`，提交 `c33315cfe2`）：
`CoreELEC-Amlogic-ng.arm-21.3-Omega-N1-r1-Phicomm_N1.img.gz`
sha256 `4789d67b845b6311693f7bb5978dfca78bc8f4e1f0b54b2001ef2a8767efb3a3`，
CI 的固件打包校验通过。镜像不含杜比视界实测结论。

必须在 N1 + 电视上标定的项目见
`n1-dolby-vision-tv-led-port.md` §7（canvas 索引、像素格式与编码、起始偏移、电视侧接受度）。

