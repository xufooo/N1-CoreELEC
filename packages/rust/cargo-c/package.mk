# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023-present Team CoreELEC (https://coreelec.org)

PKG_NAME="cargo-c"
PKG_VERSION="v0.9.17"
PKG_SHA256="95fcf50505516dfa6a941e666d1388810da9d7a9e1c623c09068faef5d50b3b9"
PKG_LICENSE="MIT"
PKG_SITE="https://github.com/lu-zero/cargo-c"
PKG_URL="https://github.com/lu-zero/cargo-c/archive/refs/tags/${PKG_VERSION}.tar.gz"
PKG_DEPENDS_HOST="cargo:host"
PKG_LONGDESC="Use Cargo-c to build and install C-compatible libraries"
PKG_TOOLCHAIN="manual"

# The v0.9.17 tag ships no Cargo.lock, so cargo resolves the whole crate graph
# from crates.io on every build.  Newer releases of the transitive dependencies
# (time, icu_*, home, cargo-util, ...) declare a rust-version far above the
# rustc we build here (1.85.1), and the build then dies with
#   error: rustc 1.85.1 is not supported by the following packages: ...
# cargo-c declares rust-version = "1.67", so let cargo's MSRV aware resolver
# pick the newest dependency versions that still honour that MSRV.  This keeps
# the build reproducible against crates.io publishing newer crates.
CARGO_MSRV_POLICY="fallback"

make_host() {
  export CARGO_RESOLVER_INCOMPATIBLE_RUST_VERSIONS="${CARGO_MSRV_POLICY}"
  cargo build --release --manifest-path ${PKG_BUILD}/Cargo.toml
}

makeinstall_host() {
  export CARGO_RESOLVER_INCOMPATIBLE_RUST_VERSIONS="${CARGO_MSRV_POLICY}"
  cargo install --profile release --path ${PKG_BUILD}
}
