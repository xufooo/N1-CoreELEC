# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2016-present Team LibreELEC (https://libreelec.tv)

PKG_NAME="newt"
PKG_VERSION="0.52.23"
PKG_SHA256="5eff268e0ba857863547f00495cb8823cdde165099009cc7a16ecbcb413535cc"
PKG_LICENSE="GPL"
PKG_SITE="https://pagure.io/newt"
# pagure 发布服务已下线；改用 Debian 池中的原始包。
PKG_URL="http://deb.debian.org/debian/pool/main/n/newt/newt_${PKG_VERSION}.orig.tar.xz"
PKG_DEPENDS_TARGET="toolchain slang popt"
PKG_LONGDESC="Newt is a programming library for color text mode, widget based user interfaces."
PKG_TOOLCHAIN="autotools"

PKG_CONFIGURE_OPTS_TARGET="--disable-nls \
                           --without-python \
                           --without-tcl"

pre_configure_target() {
 # newt fails to build in subdirs
 cd ${PKG_BUILD}
 rm -rf .${TARGET_NAME}
}

pre_configure_host() {
 # newt fails to build in subdirs
 cd ${PKG_BUILD}
 rm -rf .${HOST_NAME}
}
