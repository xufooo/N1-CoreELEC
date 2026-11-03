# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023-present Team CoreELEC (https://coreelec.org)

# Built from the reference fork on purpose: the TV-led Dolby Vision packetizer
# needs the HDMI DM serialisation that only this tree carries (see
# docs/n1-dv-implementation-plan-2026-11-02.md in OpenViking).
#
# The fork's diff does NOT apply to upstream libdovi-3.3.1 (dovi_rpu.rs
# rejects), so the source is taken from the fork itself instead of patching a
# release tarball.  PKG_SOURCE_DIR tells scripts/unpack where it extracted.
PKG_NAME="libdovi"
PKG_VERSION="d4ad4ba7e6f5acef6c7321dac0139992a082cd8f"
PKG_SHA256="e75fa34dbb755902f867383e87c28df7062baaa61c780978daaf94ed868d3d60"
PKG_SOURCE_DIR="dovi_tool-${PKG_VERSION}"
PKG_SITE="https://github.com/doppingkoala/dovi_tool"
PKG_URL="https://github.com/doppingkoala/dovi_tool/archive/${PKG_VERSION}.tar.gz"
PKG_DEPENDS_TARGET="toolchain cargo-c:host"
PKG_LICENSE="MIT"
PKG_LONGDESC="dovi_tool is a CLI tool combining multiple utilities for working with Dolby Vision."
PKG_TOOLCHAIN="manual"

pre_make_target() {
  CARGO_BASE_OPTS="--manifest-path ${PKG_BUILD}/dolby_vision/Cargo.toml \
                   --target ${TARGET_NAME}"
  CARGO_BUILD_OPTS="--library-type staticlib \
                    --profile release \
                    --prefix /usr
                    ${CARGO_BASE_OPTS}"
}

# The dovi_tool tree ships no Cargo.lock either, so the dependency graph is
# resolved from crates.io at build time.  Newer releases of the transitive
# dependencies require a rustc newer than the one we build (1.85.1) and the
# build fails with "rustc 1.85.1 is not supported by the following packages".
# dovi_tool declares rust-version = "1.65.0", so let cargo's MSRV aware
# resolver honour it instead of always picking the newest crates.
CARGO_MSRV_POLICY="fallback"

make_target() {
  export CARGO_RESOLVER_INCOMPATIBLE_RUST_VERSIONS="${CARGO_MSRV_POLICY}"
  cargo fetch ${CARGO_BASE_OPTS}
  cargo cbuild ${CARGO_BUILD_OPTS}
}

makeinstall_target() {
  export CARGO_RESOLVER_INCOMPATIBLE_RUST_VERSIONS="${CARGO_MSRV_POLICY}"
  cargo cinstall ${CARGO_BUILD_OPTS} --destdir ${SYSROOT_PREFIX}
  cargo cinstall ${CARGO_BUILD_OPTS} --destdir ${INSTALL}
}
