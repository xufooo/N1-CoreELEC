# 在新刷的镜像上还原 Kodi 用户配置（可复用操作单）

适用场景：CoreELEC 镜像重新写盘后，新系统的 `/storage` 是**空的骨架**，界面语言、媒体源、
媒体库数据库、插件、按键映射、蓝牙遥控器配对全部回到默认，需要还原。

> 本文只写**通用方法**。具体源路径、账号等属于个人环境，不入仓库。

## 0. 先搞清楚一件事：新版 /storage 是不是空的

写盘时如果用 `dd` 覆盖整块盘，**旧的 ext4 `/storage` 分区的元数据会被一起覆盖**，
老配置通常救不回来；能救回的只是"还没被覆盖的数据块"，且失去目录结构。

```sh
# 判据（在新系统上执行）
ls /storage/.kodi/userdata/          # 只有 guisettings.xml/sources.xml/profiles.xml 等骨架 = 空的
ls -la /storage/.kodi/userdata/       # 时间戳若全是镜像构建日（如 2024-02-27）= 不是老数据
cat /storage/.kodi/userdata/guisettings.xml | grep locale.language   # 被向导改成 en_gb = 新装
```

恢复优先级：

1. **老系统还能启动** → 从老系统 `/storage` 整份拷贝（最完整）
2. 老系统起不来但**老配置有 JSON-RPC 快照** → 按快照逐项重建（本文方法）
3. 都没有 → 只能重新配

## 1. 环境前提

- 新系统已启动，SSH 可用（CoreELEC 默认 `root` / `coreelec`）
- 机器上有 `curl` / `unzip`（CoreELEC 自带）

## 2. 取 Kodi 认可的地区/键盘字符串（别猜）

Kodi 的国家名带时钟后缀，来源是**语言包的 `langinfo.xml`**，不是硬编码：

```sh
unzip -p resource.language.zh_cn.zip resource.language.zh_cn/resources/langinfo.xml
# → <region name="Beijing (12h)" locale="CN"> / <region name="Beijing (24h)" locale="CN">
```

键盘布局名来自系统目录 `special://xbmc/system/keyboardlayouts/*.xml`（`chinese.xml` 的
`language="Chinese"`）：

```sh
head -12 /usr/share/kodi/system/keyboardlayouts/chinese.xml
```

## 3. 装中文语言包

语言包不在 CoreELEC 镜像里，要从 Kodi 官方插件源取。

**分支必须与 Kodi 版本匹配，否则会静默失效**。语言包从 9.0.x 到 11.0.x 与主版本绑定：

| Kodi | CoreELEC | 插件源分支 | 语言包版本 |
|---|---|---|---|
| 19 | 20.x | `matrix` | 9.0.x |
| 21 | 21.x | `omega` | 11.0.x |

取错版本的后果很隐蔽：Kodi 启动时**拒绝加载**该语言包、回退到 `en_gb`，
并**把 `guisettings.xml` 里的 `locale.language` 改回 `en_gb`**——表现为"设置没生效"，
而且下次再改也会被继续覆盖。判断方法：设置后重启 Kodi，若值又被改回 `en_gb`，就是语言包版本不对。

正确版本应包含 `resources/strings.po`（本机 omega 分支的 11.0.104 约 581 KB）：

```sh
# Kodi 21（CoreELEC 21.x）
curl -L -o zh_cn.zip \
  https://mirrors.xbmc.org/addons/omega/resource.language.zh_cn/resource.language.zh_cn-11.0.104.zip
unzip -l zh_cn.zip   # 必须能看到 resource.language.zh_cn/resources/strings.po
```


```sh
unzip -o zh_cn.zip -d /storage/.kodi/addons/     # → /storage/.kodi/addons/resource.language.zh_cn
```

装完**必须重启 Kodi**（或重启盒子）才会加载。

## 4. 还原界面设置（guisettings.xml）

必须**先停 Kodi 再改文件**，否则 Kodi 退出时会用内存里的旧值覆盖：

```sh
systemctl stop kodi
# 改 /storage/.kodi/userdata/guisettings.xml：
#   locale.language             = resource.language.zh_cn
#   locale.country              = Beijing (24h)          # 语言包 langinfo.xml 里的名字
#   locale.timezone             = Asia/Shanghai
#   locale.keyboardlayouts      = Chinese
#   locale.activekeyboardlayout = Chinese
#   videolibrary.showemptytvshows = false               # 按老系统快照还原
systemctl start kodi
```

校验：重启后文件里仍是这些值 = Kodi 认了。

### 4.1 手工编辑 guisettings.xml 的两个致命细节

**细节一：不要保留 `default="true"` 属性。**

用 sed 只替换标签内的文字、把开始标签原样保留时，会出现：

```xml
<!-- 错：Kodi 认为"值等于默认值"，忽略文本，按默认处理 -->
<setting id="locale.timezone" default="true">zoneinfo/Asia/Shanghai</setting>

<!-- 对：没有该属性才被视为用户设置 -->
<setting id="locale.timezone">zoneinfo/Asia/Shanghai</setting>
```

Kodi 自己写入用户值时也会丢掉这个属性；保留它等于白改。
判据同上：重启 Kodi 后值是否仍在（被重置 = 没生效）。

**细节二：时区值必须带 `zoneinfo/` 前缀。**

```xml
<setting id="locale.timezone">zoneinfo/Asia/Shanghai</setting>   <!-- 对 -->
<setting id="locale.timezone">Asia/Shanghai</setting>            <!-- 错，会被重置为 UTC -->
```

`locale.country` 则用**语言包 `langinfo.xml` 里声明的名字**（中文包是 `Beijing (12h)` / `Beijing (24h)`，
不是 `China`）；语言没生效时这个名字也不在可选列表里，会被重置。

### 4.2 系统时钟（与 Kodi 界面时区是两件事）

Kodi 的 `locale.timezone` 只影响界面显示。**系统时区**由 `tz-data.service` 设置：

```ini
# /usr/lib/systemd/system/tz-data.service
Environment=TIMEZONE=UTC
EnvironmentFile=-/storage/.cache/timezone
ExecStart=/bin/ln -sf /usr/share/zoneinfo/${TIMEZONE} /var/run/localtime
```

即官方持久化位置是 **`/storage/.cache/timezone`**（CoreELEC 设置里选时区时写的就是它）：

```sh
printf 'TIMEZONE=Asia/Shanghai\n' > /storage/.cache/timezone
systemctl restart tz-data.service
date                      # 应显示 CST
ls -l /var/run/localtime  # 应指向 /usr/share/zoneinfo/Asia/Shanghai
```

## 5. 还原媒体源（sources.xml）

用老系统的 `Files.GetSources` 快照重写 `sources.xml`。

**关键坑：`Files.GetSources` 上报的是 Kodi 内部形式，不是 `sources.xml` 的存储形式。**

- JSON-RPC 上报多路径源时会给出 `multipath://` + URL 编码串（例如
  `multipath://smb%3a%2f%2fHOST%2fA%2f/smb%3a%2f%2fHOST%2fB%2f`）
- 但 `sources.xml` 里真正存的是**一个源多个 `<path>` 元素**：

```xml
<sources>
  <video>
    <default pathversion="1"/>
    <source>
      <name>Combined</name>
      <path pathversion="1">smb://HOST/Share/A/</path>
      <path pathversion="1">smb://HOST/Share/B/</path>
      <allowsharing>true</allowsharing>
    </source>
  </video>
</sources>
```

如果把 `multipath://...` 串直接写进 `<path>`，Kodi 会把它当**一个字面路径**，全部源失效
（表现为源还在列表里，但打开就报错/路径不对）。

最稳的做法：**直接拿老系统 `/storage/.kodi/userdata/sources.xml` 原文件逐字覆盖**，
不要用 JSON-RPC 快照重新拼。

同样要停 Kodi 再写。

## 6. 触发媒体库扫描

```sh
kodi-send --action=VideoLibrary.Scan
```

注意：**老系统的媒体库数据库（MyVideos.db）通常随老 /storage 一起丢失**，还原的只是"源"，
内容需要重新扫描重建。扫描前先确认 SMB 凭据：老系统的 `userdata/passwords.xml` 也会丢，
电视上可能弹出凭据输入框；NAS 若允许匿名读则无需处理。

## 7. SMB 主机名解析的坑

CoreELEC 的 DNS（路由器）通常**解析不了** NAS 的 NetBIOS 名（如 `ping NAS名` 报 bad address），
但 Kodi / `smbclient` 走的是 libsmbclient 的 NetBIOS 解析，**在 Kodi 里能正常访问**：

```sh
smbclient -L //NAS名 -N        # 能 "Anonymous login successful" 就说明名字解析通了
```

所以**不要因为 `ping` 不通就判定 NAS 不可达**；也不要改源路径成 IP（会丢 NetBIOS 名称）。

## 8. 蓝牙遥控器

配对信息在 `/storage/.cache/bluetooth/<MAC>/info`，**属于系统层状态**，新系统上通常需要重新配对
（在遥控器上按一次配对键，CoreELEC 的 bluetooth 服务会自动发现并绑定）。Kodi 的按键映射在
`/storage/.kodi/userdata/keymaps/`（随老 userdata 一起丢，需重建）。

## 9. 验收清单

- [ ] 界面语言为中文，日期/时间为北京时间
- [ ] 视频源列表与老系统一致（含 multipath 源）
- [ ] 媒体库扫描能跑通、无凭据弹窗卡死
- [ ] 蓝牙遥控器可操作菜单

## 10. 严重坑：不要把新镜像的 U 盘插到正在运行的 CoreELEC 上

实测事故（2026-11-01）：把刚写好的新版 U 盘插到**另一套正在运行的 CoreELEC**（旧版本）的第二个
USB 口上，想"顺便拷文件"，结果旧系统把这张盘识别成自己的可写 COREELEC 分区，执行了首启/扩容
逻辑，**用旧系统的 `SYSTEM` 和 `kernel.img` 覆盖了新盘的启动文件**，还写了 `dtb.xml`、
`fs-resize.log`、`resolution.ini`。之后这张盘变成"新 `boot.ini` + 旧 `SYSTEM`/`kernel`"的
混合体，**完全无法启动**。

判据（在能读 FAT 的机器上比对）：

| 文件 | 正常应匹配 | 被覆盖后 |
|---|---|---|
| `SYSTEM` | 与 `SYSTEM.md5` 一致 | 大小/时间戳/md5 全部不符 |
| `kernel.img` | 与 `kernel.img.md5` 一致 | 同上 |
| 附带文件 | 无 | 多出 `dtb.xml`、`fs-resize.log`、`resolution.ini` |

**结论**：要在两套系统之间搬文件，一律走电脑中转（scp / 读卡器），
**不要**把待刷的盘插到任何正在运行的 CoreELEC 上。

恢复方式只有一个：**重新 dd 镜像**（镜像里的 `SYSTEM`/`kernel` 是唯一一致的一组）。
重刷会顺便覆盖 `/storage` 的开头，所以配置要用事先做好的备份包重新应用。
