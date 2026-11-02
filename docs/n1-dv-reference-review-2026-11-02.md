# N1 杜比视界：完整参考链路复核

日期：2026-11-02。审查起点：本地与远端 `n1-21.3` 均为
`e8580f512cf0f0b0411fc2ba626a46a4079a847b`。
本文修正早期研究中的推断，尚未形成新的固件实现或播放成功结论。

## 1. 结论与旧结论更正

社区的免授权 TV-led 路线有真实案例，也有足以复用的源码；本项目目前仅采用了其中
DM 分包、像素编码和 VSIF 部分，缺少其配套数据生产与帧同步。应按完整链路移植。

但 **P5 还需要盒子端像素重塑**。把 DM 交给电视不等于把 RPU 的 mapping 交给电视处理。
作者明确说明色度用矩阵/偏移、亮度用 EOTF/OOTF/OETF LUT 做重塑。
[作者解释，帖子 758](https://discourse.coreelec.org/t/learning-about-dolby-vision-and-coreelec-development/50998?page=38)

以下旧说法作废：

- “TV-led 让电视完成 P5 重塑，只需合成 RPU/注入元数据”。
- “作者 P5 固件缺口只在 amvideo”。静态反汇编还发现定制的 HDR2/VPP 重塑调用。
- “普通播放不调 src_fmt，因此改用 100 ms 定时器即可”。作者有解码器配套修正。
- “VSIF 的 RGB_8BIT 枚举意味着应该把物理视频切成普通 RGB 8bit”。要区分隧道信令与载荷。
- “VSVDB 注入是额外的逐帧 DM 通道”。VSVDB 是显示能力/配置数据，不能代替 DM 传输。
- “内核未支持某个 DV Core 就能证明一切软件/通用 VPP 处理都不可能”。驱动支持范围不能直接证明这些结论。
- “619ad830 已提供 GXL 的 P5 转换”。该提交仍要求 device_support_dv，不能为 N1 创造像素重塑能力。

## 2. 固定参考源与完整调用关系

| 组件 | 固定版本 | 已检查内容 |
|---|---|---|
| [common_drivers](https://github.com/doppingkoala/common_drivers/commit/eb85e7bde788a2b06c4ba808b1c4046f56a00de7) | `eb85e7bd` | 整个提交的文件改动；video.c、video_func.c、dv_injection.c、amcsc.c、amcsc_pip.c 与 HDMI 相关差异 |
| [定制 libdovi](https://github.com/doppingkoala/dovi_tool/commit/d4ad4ba7e6f5acef6c7321dac0139992a082cd8f) | `d4ad4ba7` | RPU writer、DM writer 与各 extension block 的宽度/长度布局 |
| [HEVC 解码器](https://github.com/doppingkoala/media_modules-aml/commit/ee72893ab6629c5147a5dd418a737722892898ad) | `ee72893a` | force_src_fmt 与 post_video_frame 调用 |
| [Kodi 21.2 converter](https://github.com/doppingkoala/xbmc/blob/d4ee2ad43e99374953bd0aa5f92e97aa2d4e72df/xbmc/utils/BitstreamConverter.cpp) | `d4ee2ad4` | libdovi 的实际调用与 profile 条件 |
| [Kodi 主分支 converter](https://github.com/doppingkoala/xbmc/blob/8351eac829aeb4416e2975b159428c76957c4770/xbmc/utils/BitstreamConverter.cpp) | `8351eac8` | bytestream 转换与实际 profile 条件 |
| [公开 NO overlay 原型](https://github.com/doppingkoala/common_drivers/tree/public_dv_poc) | `e13ba110` | 另一条 DRM plane 路线；不等于成熟 NG 实现 |

参考链路分为六段，缺一段不能由另一个模块的日志补证：

1. **RPU → HDMI DM**：定制 libdovi 改写序列化格式，用 `7C 01 FF` 标识自定义数据；
   DM 的字段宽度与原始 RPU 不同。上游普通 libdovi 不是自动提供此输出。
2. **解码帧得到 metadata**：HEVC 的 post_video_frame 把 aux_data 与对应 vframe 交给
   update_vframe_src_fmt。作者新增 force_src_fmt，避免仅 v4l 路径触发。
3. **预处理与缓存**：update_dv_hdr_dm_pkt 检查自定义 SEI，处理 L1/L5，按
   `vf->index & 0xff` 存入 64 槽包缓存。
4. **显示帧取对应包**：primary_render_frame 在 vsync 处理当前 dispbuf，
   dv_metadata_injection 使用当前显示帧的索引取包。不是“每解码一帧立即显示”，也不是轮询静态数据。
5. **canvas/信令**：写 GUI 缓冲，发 DV VSIF/AVI；缓冲几何、颜色路径、L5 和 GUI 处理必须配套。
6. **输出仲裁**：视频处理的发包 producer 根据当前帧是否为 DV，阻止普通 DRM/HDR10+ 覆盖。

公开 Kodi 的两个已检查版本均在 converter 中以 `guessed_profile == 7` 限制转换。
21.2 的 dv 分支相对作者 aml-4.9-21.2 仅多一个皮肤改动。
因此这些公开分支可以说明 API/机制，却还不能证明它们完整对应 2025-12 的 P5 成品。

## 3. 社区案例必须绑定版本和 profile

| 原始证据 | 可以支持的结论 | 不能推出的结论 |
|---|---|---|
| [2024 NG，帖子 341](https://discourse.coreelec.org/t/learning-about-dolby-vision-and-coreelec-development/50998/341) | 提前处理 metadata，在显示阶段复制；要求 12bit 422、4K GUI 和关闭 GUI 缩放；记录退出/字幕/暂停/4K60 问题 | 能触发 DV 不代表当时 P5 色彩正确 |
| [X96Air 测试，帖子 353–357](https://discourse.coreelec.org/t/learning-about-dolby-vision-and-coreelec-development/50998?page=18) | 测试者报告 P8 正常、P5 偏色；作者解释缺少多项式重塑 | 不应混用测试者最初写错的 NO/NG 版本号 |
| [L1/L5 与输出，帖子 363](https://discourse.coreelec.org/t/learning-about-dolby-vision-and-coreelec-development/50998/363) | 需要处理 PQ 范围和 active area；实际视频仍为 YCbCr | RGB_8BIT 枚举不等于普通 RGB8 图像转换 |
| [2025 P5 方案，帖子 758/766](https://discourse.coreelec.org/t/learning-about-dolby-vision-and-coreelec-development/50998?page=38) | 盒子做像素重塑；当年 7 月还处于单帧验证 | 旧版 DM 注入代码不是完整 P5 播放实现 |
| [2025-12 固件及测试](https://discourse.coreelec.org/t/dolby-vision-for-all-socs/57985) | 作者宣称加入 P5；Vontar X4 测试者反馈 P5/MEL 可播；另有 L8 黑屏、OSD/切源/追帧问题报告 | FEL 文件能播放不代表重建 FEL；其它芯片成功不代表 N1 成功 |
| [2026 NO overlay，帖子 16](https://discourse.coreelec.org/t/dolby-vision-for-all-socs/57985/16) | 作者称新 overlay 可避开 GUI 依赖，但只推进到触发 DV 的原型 | public_dv_poc 不是已完成的通用固件 |

本轮对上述主题及 N1/S905D/GXL 定向搜索，未找到足够明确的 N1 P5 正确播放记录。
这只是本次搜索边界，不表示全网不存在，也不表示 N1 做不到。
其中一条 T95Q 报告的 SoC 身份只是测试者自报，不能当作硬件认证。

## 4. N1 4.9 的真实差异

构建选用的解码器来自独立包，而不是 linux-amlogic 源树：
`distributions/CoreELEC/options` 选择 media_modules-aml，项目 package.mk 固定
`60561618f2bf154c1438d3c790b625ff01f215c3`。
其 vh265.c:10403 仅在 hevc->is_used_v4l 时调 update_vframe_src_fmt。
应移植作者明确的解码帧钩子，并检查重复调用/生命周期，不应以定时器代替。

NG 的 video.c:4168–4198 已有 primary_render_frame 与当前显示帧，能提供显示同步挂接位置。
移植必须检查中断上下文约束，不能把可能睡眠的 EMP/锁操作直接塞进 vsync。

**输出 producer 也与参考 5.15 不同**：amcsc.c:8100–8124 中，>=G12A 才走
hdmi_packet_process；GXL 走 hdr_tx_pkt_cb。应对准 GXL 的 producer 做有限仲裁，
保留正常停止、HDR/SDR 及热插拔处理。

**P5 的硬件处理路径不同**：

| 项 | GXL 旧 VPP | >=G12A 的 HDR2 |
|---|---|---|
| EOTF | 33 点 | 143 点 |
| video OETF | 289 点 | 149 点 |
| 调用 | set_vpp_matrix / set_vpp_lut | hdr_func / HDR2 LUT、矩阵 |
| 源码分流 | amcsc.c:5077、5613 的 G12A 分支之后 | G12A 分支内部调用并返回 |

已下载作者 2025-12 固件的 arm64 Image，用恢复符号的 ELF 和 LLVM objdump 静态检查：
hdr_func.part.0 在 `0xffffff80099f6b14` 调用 dv_need_reshaping，并处理与 HDR2
143/149 点结构吻合的数组。此为**静态调用证据**，不代表实机执行或 GXL 兼容性。
它推翻了“只缺 amvideo”的旧判断；还不能证明作者如何为 GXL 生成和应用重塑表。
本次 REA CLI doctor 未成功，未安装/修改分析环境；上述反汇编来自普通 LLVM 工具，不是 REA Evidence。

## 5. 数据格式已有公开校验样例

[libdovi issue 303](https://github.com/quietvoid/dovi_tool/issues/303) 包含作者的格式说明及捕获字节。
上游维护者没有接受该 writer 变更，不能把普通 libdovi 的存在当作已集成此能力。

已取作者 [公开捕获样例](https://github.com/quietvoid/dovi_tool/issues/303#issuecomment-2237841066)，
181 字节，SHA256 `1dac69a2b6dc8070a8f009a45c59a8875efe742792b7679ed078f238d5fce91f`：
按参考格式完整解析出 9 个 extension block，恰好消费全部字节。
相同解析器读本地样片的首个 235 字节 raw RPU 时，第一个 extension 长度即超出输入。
这验证了两者不能直接互换，不是 HDMI 实测。

此前还用提取的实际 C 函数对比 1–255 字节分包、CRC 和全部像素编码，结果一致。
两项测试证明格式/编码部分，均不证明 P5 像素结果或电视识别。

## 6. 统一修改前必须闭合的内容

1. **独立 DM writer**：保留正常 libdovi writer 的语义，另建明确的 HDMI DM 输出接口；
   对公共捕获向量、CMv2.9/4.0、use_prev RPU、缺失/非法元数据做比较。
2. **解码帧到显示帧**：配套 vh265 钩子、metadata 缓存与 primary_render_frame 消费；
   索引复用、seek、flush、停止和切换解码器须有失效/世代管理。
3. **P5 像素处理**：把 mapping 系数、矩阵、LUT 计算和 GXL 挂接查清。
   p5_to_p81 改 metadata 不会替代像素处理；不能把 HDR2 表直接写给旧 VPP。
4. **canvas 安全与格式**：由真实 framebuffer 获取索引/stride/page/容量；验证所有偏移、
   repeat 与乘法范围，处理 GUI 缩放/翻页及 L5。不能继续照抄 4K 偏移。
5. **信令与退出**：按当前有效的 DV 显示帧仲裁 GXL 的 HDR10/HDR10+ producer；
   失败时回退，停止/禁用/切片/热插拔恢复 AVI、VSIF、矩阵/LUT 和 GUI。
6. **一次候选构建前验收**：全部补丁应用、相关对象真实交叉编译/链接、DM与分包向量、
   缓冲边界和状态转换验证通过，才发起完整 image 构建。

公开参考足以纠正 P8/MEL 的数据链路设计。P5→GXL 的 LUT 生成与调用尚未闭合，
不应把仍缺这段的固件命名为“P5 修复完成”。整镜像编译完成与实际正确播放须分别验收。

复现材料保存在本地 `.work/research/reference-chain/`：固定源码、完整提交 diff、
source-files.json、check_dm_vector.py、捕获向量、解析结果与限定地址范围的反汇编。
这些材料不包含个人显示设备资料；本报告不发布实机原始日志。
