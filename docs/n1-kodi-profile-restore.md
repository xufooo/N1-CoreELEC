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

语言包不在 CoreELEC 镜像里，要从 Kodi 官方插件源取（Kodi 19 = `matrix` 分支）：

```sh
# 目录: https://mirrors.xbmc.org/addons/matrix/resource.language.zh_cn/
curl -L -o zh_cn.zip \
  https://mirrors.xbmc.org/addons/matrix/resource.language.zh_cn/resource.language.zh_cn-<ver>.zip
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

## 5. 还原媒体源（sources.xml）

用老系统的 `Files.GetSources` 快照重写 `sources.xml`。**multipath 源要逐字照抄**（Kodi 存的是
URL 编码后的多路径串，路径之间用 `/` 分隔）：

```xml
<sources>
  <video>
    <default pathversion="1"/>
    <source>
      <name>Some Videos</name>
      <path pathversion="1">smb://HOST/Share/Movies/</path>
      <allowsharing>true</allowsharing>
    </source>
    <source>
      <name>Combined</name>
      <path pathversion="1">multipath://smb%3a%2f%2fHOST%2fA%2f/smb%3a%2f%2fHOST%2fB%2f</path>
      <allowsharing>true</allowsharing>
    </source>
  </video>
</sources>
```

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
