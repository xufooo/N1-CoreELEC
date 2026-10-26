# SPDX-License-Identifier: GPL-2.0-or-later
# Boot-file packaging only; the factory bootloader remains in use.
PKG_NAME="u-boot-Phicomm_N1"
PKG_VERSION="1.0"
PKG_LICENSE="GPL"
PKG_DEPENDS_TARGET="toolchain linux u-boot-script"
PKG_TOOLCHAIN="manual"
PKG_NEED_UNPACK="${PKG_DIR}"

make_target() {
  :
}

makeinstall_target() {
  local dtb="$(get_install_dir linux)/usr/share/bootloader/device_trees/meson_gxl_s905d_phicomm_n1.dtb"
  test -s "${dtb}" || die "N1 DTB was not built by linux:target"
  mkdir -p "${INSTALL}/usr/share/bootloader"
  cp -v "${dtb}" "${INSTALL}/usr/share/bootloader/Phicomm_N1_dtb.img"
}
