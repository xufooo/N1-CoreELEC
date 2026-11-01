# Building N1

Use the **N1 CoreELEC 21.3** Actions workflow. Target `audit` checks the actual
patch stack, NTFS package hooks, DTB and U-Boot script compilation; it does not
compile a firmware. Target `image` produces USB firmware. Runs are manual;
there is no scheduled build and no automatic release publication.

On a supported non-root Linux x86_64 build host with CoreELEC dependencies:

```sh
bash tools/n1/build.sh image
python3 tools/n1/verify_image.py target
```

The image build retains source/compiler caches, uses the upstream package
autoremove mechanism, records build/resource logs and uploads a manifest.
The ephemeral runner's unused Android/.NET/GHC/CodeQL SDKs are removed from an
explicit allowlist. No user disks or running device are touched.

Artifacts:

- `*Phicomm_N1.img.gz`: new USB installation on a **different** USB stick.
- `*.tar`: update candidate for this fork after validation; not a supported
  in-place migration from the user's 3.14-based 9.2.7 installation.
- SHA256 sums and source manifest.
- Build logs and firmware-content verification result.

Use a single test stick at a time: UUIDs avoid relying on COREELEC/STORAGE labels
shared with the original stick. This does not alter factory U-Boot or configure
a previously unconfigured box to boot USB.

The initial workflow timeout is 350 minutes. Whether the hosted runner has
enough real disk/time is measured, not assumed. Cache restoration is an
optimization, not proof of a successful or reproducible build. Baseline and
experimental DV code must remain separately identifiable. The DV experiment
is therefore carried by its own device patch
(`projects/Amlogic-ce/devices/Amlogic-ng/patches/linux/linux-20-tv-led-dolby-vision-injection.patch`),
not by edits to shared upstream sources.

## 待办：镜像默认关闭自动升级（2026-11-01 记录，尚未实施）

**已实际发生的风险**：自编镜像刷入盒子后，CoreELEC 的自动升级会把**官方发布包**下载到
`/storage/.update/`，并在**下次重启时应用**，后果是：

- 官方 `SYSTEM`/`kernel` 覆盖掉我们的 TV-led 杜比视界补丁；
- CoreELEC 新版本已停止 GXL（S905D）支持，N1 升上去极可能无法启动。

实测证据（2026-11-01，`CoreELEC 21.3-Omega-N1-r1` 首次启动后）：`/storage/.update/` 中出现
`CoreELEC-Amlogic-ng.arm-21.3-Omega.tar`（273,981,440 B，顶层目录
`CoreELEC-Amalogic-ng.arm-21.3-Omega/`，**非本仓库产物**），已删除，`/storage/.update/` 现为空。

**官方关闭入口（用户侧，已确认）**：

```
设置 → CoreELEC → Updates → Automatic Updates = OFF
```

参考：CoreELEC Wiki `coreelec:ce_addon_updates`、`coreelec:updates`（Disable Auto-Update）。
同一页还有 `Submit Statistics`、`Show Update Notifications` 可一并关闭。

实现机制（`service.coreelec.settings/defaults.py`）：

```python
updates = {
    'ENABLED': not os.path.exists('/dev/.update_disabled'),
    'UPDATE_REQUEST_URL': 'https://update.coreelec.org/updates.php',
    'LOCAL_UPDATE_DIR': '/storage/.update/',
}
```

即开关等价于 `/dev/.update_disabled` 是否存在；`/dev` 为内存盘，每条启动由设置插件按保存值重建。

**待做的镜像级改动**（目标：刷机后默认即关闭，无需手动操作）：

1. 在 `projects/Amlogic-ce/packages/addons/` 下加项目级覆盖包，对 `service.coreelec.settings`
   的 `defaults.py` 打补丁，把 `ENABLED` 默认置为 False；或
2. 随 SYSTEM 预置一个 oneshot 服务，在 Kodi 启动前创建 `/dev/.update_disabled`；
3. 重新走 CI 的 `image` 目标出镜像。

**验收标准**：

- [ ] 刷机后 `/dev/.update_disabled` 存在
- [ ] 启动后 `/storage/.update/` 保持为空（不出现官方 tar）
- [ ] Kodi 设置页仍可手动改回（不阻断手动升级路径）
- [ ] `/etc/os-release` 仍为自编标识（`VERSION="21.3-Omega-N1-r1"`）
