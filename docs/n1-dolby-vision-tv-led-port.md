# N1 TV-led 杜比视界：移植实施说明

> 状态：**已入库、未编译、未上机**。本文件描述已落地的内核补丁、如何启用、以及必须在实机上标定的项目。
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

## 8. 验收

沿用 `docs/n1-acceptance.md`：P8 / P5 分别单独测试；**DV 徽标不能作为重塑正确的证据**，
必须逐项核对亮度、色彩、字幕与音频。

## 9. 参考

- 公开参考实现：`doppingkoala/common_drivers@eb85e7bd` → `drivers/media/video_sink/dv_injection.c`
- 4.9 实测依据：`doppingkoala` 的 21.1 NG 构建（`amvideo.inject_osd_metadata` 等 11 个参数）
- 同代 21.3 成品：`avdvplus`（Player-led 路线，含 `inject_dolby_vsvdb()` 50 行可借鉴）
- 社区口径：ZNDS 2024-08 "无杜比授权播放杜比视界…支持 s905x2 那代开始"
