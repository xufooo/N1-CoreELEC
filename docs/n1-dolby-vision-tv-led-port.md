# N1 TV-led 杜比视界：移植实施说明

> 状态：**已入库、内核编译通过、整机镜像已构建、未上机**。
> - 2026-10-27 CI `kernel` 目标：exit 0（`CC …/dv_injection.o` + `LD …/amvideo.o`）
> - 2026-10-28 CI `image` 目标：exit 0，产出 N1 USB 镜像（见 §8）
> - **仍未上机**：功能默认关闭，且 7 项标定未做
>
> 本文件描述已落地的内核补丁、如何启用、以及必须在实机上标定的项目。
> 原理与取证过程见 [n1-dolby-vision-2026.md](n1-dolby-vision-2026.md) §9/§10。

## 1. 为什么是这条路

N1（S905D / GXL）没有杜比授权的 DV Core，`dovi.ko` 也拿不到，因此 **Player-led**（盒子自己重塑画面）
这条路在硬件上被排除。

**TV-led** 不需要授权：盒子只负责把杜比视界的"说明书"（Display Management 元数据）交给电视，
由电视自己完成重塑。N1 的 HDMI TX 与 21.3 基线都已具备所需能力：

| 能力 | 基线里的现成实现 |
|---|---|
| 发 Dolby VSIF | `vinfo->vout_device->fresh_tx_vsif_pkt()`（`hdmi_tx_main.c:1863`） |
| TV-led 电视端开关 | `hdmitx20.dovi_tv_led_bt2020` / `dovi_tv_led_no_colorimetry`（`hdmi_tx_main.c:108-109`） |
| 另一种元数据通道 | `dolby_vision_update_vsvdb_config()`（`amdolby_vision.c:1711`） |
| 拿到 GUI 画布 | `canvas_read()`（`video_keeper.c:154`） |
| 拿到码流 SEI | `update_vframe_src_fmt(vf, sei, size, …)`（`video.c:7663`） |

## 2. 已入库的内容

| 文件 | 说明 |
|---|---|
| `projects/Amlogic-ce/devices/Amlogic-ng/patches/linux/linux-20-tv-led-dolby-vision-injection.patch` | 内核补丁（5 个文件，+512 行） |
| `projects/Amlogic-ce/devices/Amlogic-ng/linux/linux.aarch64.conf` | 新增 `CONFIG_AMLOGIC_MEDIA_VIDEO_DV_INJECTION=y` |

补丁内容（对 `linux-amlogic @ amlogic-4.9-20` 生成，已用 `git apply --check` 对干净树验证）：

- **新增** `drivers/amlogic/media/video_sink/dv_injection.c`
  DM 元数据 → 128 字节分包（CRC32 在末 4 字节）→ 每 bit 变一个像素 → 写入 OSD canvas 左上角 → 发 VSIF
- **新增** `include/linux/amlogic/media/video_sink/dv_injection.h`
- **改** `drivers/amlogic/media/video_sink/video.c`：在 `update_vframe_src_fmt()` 末尾调用
  `dv_injection_process_frame(vf)`
- **改** `drivers/amlogic/media/video_sink/Makefile` / `Kconfig`：新增 `CONFIG_AMLOGIC_MEDIA_VIDEO_DV_INJECTION`

分包与像素编码遵循公开参考实现（`doppingkoala/common_drivers` 的 `dv_injection.c`），
仅适配 4.9 的 API（`canvas_read()` / `fresh_tx_vsif_pkt()`）。

## 3. 数据通路

```
码流 RPU ──(Kodi/libdovi 提取 DM 块)──> hex 字符串
      │  写入 /sys/module/amvideo/parameters/dv_metadata
      ▼
内核 dv_injection: 分包 → CRC32 → bit→像素
      │  canvas_read(osd_canvas) → phys_to_virt → 写左上角
      ▼
画面顶部像素携带元数据  +  HDMI VSIF（DV STD）
      ▼
电视自行重塑 → 屏幕进入杜比视界
```

## 4. 内核参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `dv_injection_enable` | `0` | **总开关**，置 1 才注入 |
| `dv_metadata` | `""` | DM 元数据（hex 字符串），写入即触发重新分包 |
| `dv_metadata_len` | `0` | 元数据字节数；0 表示按 hex 长度推断 |
| `osd_canvas` | `0` | 写入哪个 canvas（**需实机标定**） |
| `osd_pixel_offset` | `0` | canvas 内起始像素偏移（**需实机标定**） |
| `bytes_per_pixel` | `4` | canvas 像素字节数（4=ARGB32；12bit 422 可能需要 2，**需实机标定**） |
| `odd_pattern` | `0xFFFFFFFF` | bit=1 的像素值（**需实机标定**） |
| `even_pattern` | `0xFF000000` | bit=0 的像素值（**需实机标定**） |
| `packet_repeat` | `3` | 每个包重复次数 |
| `always_send_vsif` | `1` | 每帧都发 VSIF |
| `dv_injection_log_level` | `0` | 日志级别 |

## 5. 启用步骤（实机）

```sh
# 1) Kodi：视频设置 → 12-bit 4:2:2；GUI 分辨率 3840x2160；开启 "Disable GUI scaling"；重启
# 2) 灌入元数据（hex，DM 块字节）
echo "<DM_METADATA_HEX>" > /sys/module/amvideo/parameters/dv_metadata
# 3) 打开注入
echo 1 > /sys/module/amvideo/parameters/dv_injection_enable
# 4) 观察
dmesg | grep -i "dv injection"
```

## 6. 元数据从哪来

当前实现**从用户态喂字节**，Kodi 侧用 libdovi（本项目已链接，见
`projects/Amlogic-ce/packages/multimedia/libdovi`）从码流取 RPU 并提取 DM 块。

> 说明：4.9 内核里码流 SEI 是 Amlogic 的 7-bit 打包格式，且 RPU 解析依赖 DV Core 的
> `metadata_parser`（GXL 上没有 dovi.ko，取不到）。所以**由 Kodi 侧解析并喂字节**是当前最简路径；
> 后续若需要内核自动取，可再实现 4.9 的 RPU 解包（参考 5.15 实现里的 RPU/DM 提取部分）。

## 7. 必须在实机上标定的项目

这些是参考实现无法直接给出、需要 N1 + 电视实测确定的：

1. **目标 canvas 索引**（`osd_canvas`）：4.9 里 GUI/OSD 与视频各用哪些 canvas
2. **canvas 像素格式**（`bytes_per_pixel` / `odd_pattern` / `even_pattern`）：
   12-bit 4:2:2 输出下的 canvas 布局与像素编码
3. **起始偏移与占用行数**（`osd_pixel_offset`）：元数据像素必须落在画面最顶端且不破坏画面
4. **电视侧**：目标电视是否接受"顶部像素 + VSIF"的 TV-led 形式（读 EDID `rxcap.dv_info` 确认）
5. **VSIF 模式**：当前固定 DV STD（`dobly_vision_signal = 1`）；若电视要求 LL 或 tunnel 需调整
6. **与 Kodi GUI 的冲突**：作者原始方案要求"Disable GUI scaling"，且暂停/按信息键会黑屏

## 8. 已构建的镜像

| 项 | 值 |
|---|---|
| CI run | `40557456110`（源码提交 `c33315cfe2`） |
| 镜像 | `CoreELEC-Amlogic-ng.arm-21.3-Omega-N1-r1-Phicomm_N1.img.gz`（231,503,774 B） |
| sha256 | `4789d67b845b6311693f7bb5978dfca78bc8f4e1f0b54b2001ef2a8767efb3a3` |
| 更新包 | `CoreELEC-Amlogic-ng.arm-21.3-Omega-N1-r1.tar`（277,739,520 B） |
| sha256 | `22083a8a75d8e1c7e860f10f0c54d718fb0f06e7593c75289680a928dbd4ab06` |
| 本地副本 | `.work/firmware/`（仓库内，不入库） |

该次构建的日志证据：`patching file …/dv_injection.c` → `CC …/dv_injection.o` →
`[140/357] [DONE] install linux:target`，随后 CI 的 `verify_image.py` 对打包镜像校验通过。

> 该镜像**不含**杜比视界实测结论：功能默认关闭，需要按 §5/§7 手工开启与标定。

## 8.1 构建环境需要记住的两件事

1. **host 工具用 `-march=native` 编译**：跨 CPU 家族复用 ccache 会产出带本机不支持指令的
   二进制（`bison: Illegal instruction`、`tar: Child died with signal 4`）。编译缓存键已加
   CPU 指纹，源码缓存单独保存。
2. **21.3 基线的部分上游源已失效**：rtmpdump、libmpeg2、megatools、udevil、grub、newt、
   wireguard-linux-compat 各有一个项目级覆盖（`projects/Amlogic-ce/packages/`），改用仍然
   存在的镜像；其中 4 个字节完全相同、哈希不变。

## 9. 验收

沿用 `docs/n1-acceptance.md`：P8 / P5 分别单独测试；**DV 徽标不能作为重塑正确的证据**，
必须逐项核对亮度、色彩、字幕与音频。

## 9. 参考

- 公开参考实现：`doppingkoala/common_drivers@eb85e7bd` → `drivers/media/video_sink/dv_injection.c`
- 4.9 实测依据：`doppingkoala` 的 21.1 NG 构建（`amvideo.inject_osd_metadata` 等 11 个参数）
- 同代 21.3 成品：`avdvplus`（Player-led 路线，含 `inject_dolby_vsvdb()` 50 行可借鉴）
- 社区口径：ZNDS 2024-08 "无杜比授权播放杜比视界…支持 s905x2 那代开始"

## 10. 首次上机操作单

按顺序做，**每一步都先看输出再进下一步**。

### A. 启动与模块确认

1. U 盘插 N1，上电，HDMI 接电视，等 CoreELEC 起来。
2. 确认我们的模块在核心里：

```sh
ls /sys/module/amvideo/parameters/ | grep dv_
# 期望：dv_injection_enable  dv_metadata  dv_metadata_len
#       osd_canvas  osd_pixel_offset  bytes_per_pixel
#       odd_pattern  even_pattern  packet_repeat
#       always_send_vsif  dv_injection_log_level
dmesg | grep -i "dv injection"
```

> 若 `ls` 没有输出，说明刷的不是带补丁的镜像（或内核没加载 amvideo）。

### B. 目标电视是否支持 TV-led（只读取证）

```sh
cat /sys/class/drm/card*-HDMI-A-1/edid | xxd | head -40
```

看 EDID 里的 `rxcap.dv_info`（厂商扩展块）。同时在电视设置里确认有 Dolby Vision 选项、
以及是否需要手动切到 DV 模式。

### C. 取一份杜比视界样片的 DM 元数据

镜像自带 `dovi_tool` 3.3.1：

```sh
dovi_tool extract -s /storage/sample.mkv        # 先看 RPU/DM 结构
dovi_tool generate --profile 8 ...             # 需要重建时用
```

需要的是 **DM 块字节**（不是完整 RPU）。拿到后转成十六进制字符串。

### D. 灌入并开启

```sh
echo 1 > /sys/module/amvideo/parameters/dv_injection_log_level
echo "<DM_HEX>" > /sys/module/amvideo/parameters/dv_metadata
echo 1 > /sys/module/amvideo/parameters/dv_injection_enable
dmesg | tail -20
```

期望日志：`dv injection: N bytes of DM metadata`、`dv injection: formed M packets`、
`dv injection: metadata written to canvas X`。

### E. 标定（每次只改一个参数，改完立刻看画面）

| 顺序 | 参数 | 试什么 | 判据 |
|---|---|---|---|
| 1 | `osd_canvas` | 0,1,2,… | dmesg 不再出现 "canvas N not valid" |
| 2 | `bytes_per_pixel` | 4 → 2 | 画面顶部像素形态是否正确（不撕裂、不花屏） |
| 3 | `odd_pattern` / `even_pattern` | 默认 0xFFFFFFFF / 0xFF000000，按 12bit 422 实际编码调整 | 电视是否识别出 DV 元数据 |
| 4 | `osd_pixel_offset` | 0 → 递增 | 元数据像素必须落在画面最顶端且不可见 |
| 5 | `packet_repeat` | 3 → 1/2 | 电视端是否稳定识别 |

Kodi 侧要求：视频输出 **12-bit 4:2:2**、GUI 分辨率 **3840x2160**、开启 **Disable GUI scaling**；
否则 GUI 会覆盖注入的顶部像素（作者原始实现里暂停/按信息键会黑屏）。

### F. 验收

按 [n1-acceptance.md](n1-acceptance.md)：DV 徽标不能作为重塑正确的证据，必须逐项核对
亮度、色彩、字幕与音频；P5 与 P8 分开测。

## 11. U 盘静态验证（2026-10-28）

镜像由用户写入 8.1 GB 外置 U 盘（`/dev/disk2`）后，对**盘上实际内容**做的只读核验。

### 11.1 分区与文件

| 项 | 结果 |
|---|---|
| 写前布局 | `COREELEC` FAT32 536.9 MB + `Linux` 7.5 GB（旧镜像残留） |
| 写后布局 | `COREELEC` FAT32 536.9 MB + `Linux` **33.6 MB** + 7.5 GB 未分配 —— 与本镜像 MBR 一致 |
| 镜像 MBR | 0x55AA 有效；分区1 FAT32(LBA) 起始 8192、1048576 扇区；分区2 Linux 起始 1056768、65536 扇区 |
| FAT 内容 | `SYSTEM` `kernel.img` `dtb.img` `uInitrd` `boot.ini` `s905_autoscript` `aml_autoscript` `config.ini` `device_trees/` 齐全 |
| `boot.ini` | `boot=UUID=2710-1342 disk=UUID=a078a0c8-… BOOT_IMAGE=kernel.img`（UUID 引导，无旧配置残留） |
| `dtb.img` | 含 `meson_gxl_s905d_phicomm_n1`（N1 专用 DTB） |
| `kernel.img` | 28,051,464 B，头部 `ARM\x64` @56 —— 合法未压缩 arm64 Image |

### 11.2 DV 模块确实在这份内核里

对 U 盘上的 `kernel.img` 直接做字符串检索，11 个模块参数名**全部命中**：

```
dv_injection_enable  dv_metadata  dv_metadata_len  osd_canvas
osd_pixel_offset  bytes_per_pixel  odd_pattern  even_pattern
packet_repeat  always_send_vsif  dv_injection_log_level
```

日志字符串同样在位：`dv injection: module loaded`、`dv injection: canvas %u not valid`、
`dv injection: metadata written to canvas %u`、`dv injection: formed %u packets from %u bytes`。

> 这一步把"模块编进了内核"从**构建日志推断**升级为**从出厂二进制读出的事实**。

### 11.3 与构建产物的逐字节比对

| 比对对象 | 结果 |
|---|---|
| U 盘 `kernel.img` vs 本地 `.img` 内偏移 `0xf00200` | ✅ 整份逐字节一致 |
| U 盘 `SYSTEM` vs 更新包 `.tar` 的 `/target/SYSTEM` | ✅ 整份逐字节一致（md5 `9ff16ed999113c72a4e619db6db76468`） |
| U 盘 `kernel.img` md5 vs 盘上 `kernel.img.md5` | ✅ `7146d7b6048d4af76656d5654e89b0ed` |

### 11.4 尚未验证的部分

以上全部是**静态**结论。以下必须实机确认，当前没有任何证据：

- 模块是否在 N1 上正常加载（`/sys/module/amvideo/parameters/` 是否出现那 11 个参数）
- 元数据能否被正确写入目标 canvas（canvas 索引、像素编码、起始偏移待标定）
- 目标电视是否接受"顶部像素 + VSIF"的 TV-led 形式
- 重塑后的亮度、色彩、字幕与音频是否正确（按 `n1-acceptance.md` 逐项核对，DV 徽标不作数）
