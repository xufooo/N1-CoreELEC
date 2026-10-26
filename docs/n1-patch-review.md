# N1 / CoreELEC 21.3 补丁审查

审查日期：2026-10-26。基线和源码 hash 见 [n1-sources.md](n1-sources.md)。
本轮检查的是实际源码、打包脚本及可获得的社区提交；设备启动、播放和听音没有完成。

## 逐项决定

| 项目 | 源码证据与结论 | 本项目处理 | 剩余验收 |
|---|---|---|---|
| N1 USB 启动 / DTB | Damenly `53b9f488` 提供 N1 DTS、raw Image、独立 uInitrd；工厂 U-Boot 加载方式与官方 Generic Android boot.img 不同 | 移植必需适配，仍用官方 21.3 内核；DTS 进入内核正常 dtbs 目标 | Linux DTB 编译、完整构建、N1 启动 |
| 有线 / 无线 MAC | 内核 `stmmac_platform.c` 注册 `mac=`；`wifi_dt.c` 注册 `mac_wifi=`。固定 ap6xxx 源码的 `dhd_gpio.c:dhd_wlan_get_mac_addr()` 调用 `wifi_get_mac()`。N1 boot.ini 重设 bootargs 后没有传入工厂环境中的地址 | USB 脚本在导入 boot.ini 后追加非空 `mac`（其次 `ethaddr`）和 `mac_wifi`。没有写死任何设备地址，也没有调用 saveenv | 确认实机工厂环境包含这些变量，核对 Android/CE 地址；变量缺失时不得宣称已恢复工厂 MAC |
| YYYKQ 确认键 | 21.3 的 `packages/sysutils/systemd/hwdb.d/70-local-keyboard.hwdb` 已有 `b0005v0416p0300` 的 `c0041=enter`；`scripts/install` 会把 hwdb 装入 SYSTEM | 不重复补丁；新增最终 SYSTEM 内容检查 | 核实实际遥控器 VID/PID，实机检查确认键 |
| 蓝牙重连 | 21.3 已带 `linux-02-fix_bluetooth_reconnect.patch`，针对 L2CAP unknown-options 协商；不能推导为所有遥控器/双系统配对问题均已解决 | 保留上游补丁；不全局禁用 ERTM、不覆写配对密钥 | 冷启动、重连、双系统切换分别验证 |
| NTFS 自动挂载 | `NTFS3G=yes`；ntfs-3g 包安装 `/usr/sbin/mount.ntfs -> /usr/bin/ntfs-3g`；但 udevil 又生成同路径的 ntfs3 wrapper。NG 内核树没有 `fs/ntfs3`，配置也没有 NTFS3 驱动 | **已修复**：启用 NTFS3G 时 udevil 不再生成竞争 helper；以 NTFS3G 标记打包 stamp。未启用 NTFS3G 的现代内核配置保留原 wrapper | 安装 hook 两种配置测试已通过；最终 SYSTEM 仍需检查，实机插盘/热插拔待测 |
| Atmos/直通退出后无声 | 固定 Kodi `AESinkALSA.cpp:Initialize()` 会按新格式设置 PCM/直通和 mixer；`Deinitialize()` 关闭 PCM。joyo1 仅给出切换音频设备/重启的规避办法，未提供可归属的修复提交 | **不加入推测性音频 reset**。不能仅凭这些调用断言已修复，也不能断言是唯一根因 | 需要实际 ALSA 卡型、Kodi 日志、退出前后 mixer 状态与电视/功放链路 |
| 强制 YCbCr 4:2:2 | RuralHunter 旧默认含 `force422`；21.3 固定 Kodi 中没有找到同名设置的实现 | 不导入过时设置，也不强制所有片源使用某一色度格式 | 根据实际 HDMI 能力测试，不作为 P5 修复 |
| SMB 最低协议 | 旧默认 `smb.minprotocol=1` 在当前 Kodi 中表示 SMBv1；默认值是 0（不强制） | 保留 21.3 默认，不以降低协议版本作为通用加速 | NAS 协商/吞吐实测 |
| WireGuard / commons-text | 21.3 已是 WireGuard `1.0.20220627`、commons-text `1.12.0`，与 Damenly 的目标版本一致 | 不重复回移；不为“优化”扩大网络/JRE功能范围 | 对应功能需要时再测 |
| ipset、路由 netfilter、Docker/小雅、IPTV预装 | 不属于 N1 基础播放链修复 | 不默认整合 | 可选功能另行处理 |
| 内置 eMMC 安装 | Damenly 21.0 曾明确禁用 installtoemmc | 首版只提供 USB 试机流程，不声称旧 9.2.7 可直接覆盖升级 | 后续另行审核分区/备份/迁移流程 |

## NTFS 回归证据

实际执行上游 21.3 的 udevil 安装 hook，在 `NTFS3G=yes` 时仍生成：

```sh
exec /usr/bin/mount -t ntfs3 "$@"
```

修改后执行实际 hook：`NTFS3G=yes` 不再生成此路径；`NTFS3G=no` 仍生成原可执行 wrapper。
测试脚本：`python3 tools/n1/test_packages.py -v`。这验证打包行为，不等同真实磁盘挂载。
最终固件检查额外要求 mount.ntfs 为 ntfs-3g 链接且二进制存在。

## 杜比视界：源码追溯结果

1. [2025-12 P5 实验版](https://discourse.coreelec.org/t/dolby-vision-for-all-socs/57985)
   作者称新增 P5、缺 FEL。论坛反馈包含其他 SoC 的播放与黑屏问题；未找到明确 N1 实测。
2. [作者 Kodi 分支](https://github.com/doppingkoala/xbmc)的
   `dv-doppingkoala-21.2` 相对他自己的 `aml-4.9-21.2` 只有皮肤修改；
   这不足以确定完整实验代码在哪。旧分支相对官方 21.3 含大量历史差异，不能整支替换。
3. `common_drivers:dv-doppingkoala` 的 `eb85e7bd`（2024-08-21）包含
   `dv_injection.c`，属于 5.15 的媒体/OSD/HDMI 代码组合，不是可直接应用的 N1 4.9 补丁。
4. `common_drivers:public_dv_poc` 的 `e13ba110`（2026-01-03）修改 DRM plane、
   OSD 和 metadata injection；`xbmc:public_dv_pov` 的 `ce7c6c62`（2026-02-23）
   新增 DRM YUV overlay，并有硬编码 plane id 44、3840x4 缓冲等实验假设。
   我们固定的 4.9 Kodi 甚至没有对应的 `AMLDisplay.cpp`；不能直接 cherry-pick。
5. [作者 media_modules-aml](https://github.com/doppingkoala/media_modules-aml) 的
   `ee72893a`（2024-08-21）只是旧版 src_fmt 更新；它不是完整的 linux-amlogic 内核库。
   先前把它与内核 SHA 直接 compare 的 HTTP 404 不能作为“缺源码”证据。
6. [作者对旧版的解释](https://discourse.coreelec.org/t/learning-about-dolby-vision-and-coreelec-development/50998/621)：
   metadata injection 本身不解决 P5 视频重塑；P5 需要实际改变像素，而不只是发送不同 metadata。
   这说明必须找到后续 P5 实现及配套版本，不能拿 2024 的注入代码冒充 2025 的修复。

**决定：当前不把任何上述 DV 代码合入基础版。** 尚未核实 2025 P5 二进制对应的完整
NG 源码组合，不能据此承诺移植成功。输出为电视端 DV 与转成 HDR10/SDR 是不同实现，
需在显示设备能力明确后选择。FEL 不列入第一轮目标。

## 本轮验证边界

- 已完成：实际上游源码检查、NG 适用补丁栈在固定内核上依次应用、NTFS 安装 hook 回归、
  shell/Python/workflow 静态检查。
- Linux 源码审计 CI 还会实际编译 DTB 和 U-Boot 脚本。
- 没有完成：完整内核/Kodi 编译、最终固件内容检查、N1 启动、连续播放、视听检查。
- 初轮 CI 是宿主依赖检查失败后取消；不把它算作编译成功。

相关原始问题：[NTFS 定制版报告](https://www.znds.com/tv-1252495-1-1.html)、
[确认键实测报告](https://www.znds.com/tv-1225824-1-6.html)、
[俄文社区同类扫描码记录](https://4pda.to/forum/index.php?showtopic=990018&st=4760)。
