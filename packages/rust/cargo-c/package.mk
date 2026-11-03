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

# The MSRV aware resolver cannot help with crates that under-declare their
# MSRV.  ignore >= 0.4.24 is edition 2024 and uses let-chains, which need
# rustc 1.88+, yet it declares no rust-version at all, so the resolver happily
# selects 0.4.30 and the build dies with
#   error[E0658]: `let` expressions in this position are unstable
# ignore 0.4.23 is the last release that is still edition 2021 and free of
# let-chains; the same version is already compiled successfully elsewhere in
# this build (cargo 0.69.1 from the rust package ships it in its own lockfile).
CARGO_IGNORE_PIN="0.4.23"

cargo_prepare_lock() {
  export CARGO_RESOLVER_INCOMPATIBLE_RUST_VERSIONS="${CARGO_MSRV_POLICY}"
  if [ ! -f "${PKG_BUILD}/Cargo.lock" ]; then
    cargo generate-lockfile --manifest-path ${PKG_BUILD}/Cargo.toml
  fi
  cargo update --manifest-path ${PKG_BUILD}/Cargo.toml -p ignore --precise ${CARGO_IGNORE_PIN} || \
    echo "warning: could not pin ignore to ${CARGO_IGNORE_PIN} (not in the graph?)"
}

make_host() {
  cargo_prepare_lock
  cargo build --release --manifest-path ${PKG_BUILD}/Cargo.toml
}

makeinstall_host() {
  cargo_prepare_lock

  # `cargo install --path` resolves the dependency graph again from scratch
  # and ignores the Cargo.lock we pinned above, so it picked ignore 0.4.30
  # again and the install step died with the same let-chains error.  Install
  # the binary that was already built with the pinned lock instead, the same
  # way packages/rust/cargo and packages/rust/bindgen-cli do it.  ${TOOLCHAIN}/bin
  # is the first entry of PATH (config/path), so `cargo cbuild` finds cargo-c.
  cargo build --release --manifest-path ${PKG_BUILD}/Cargo.toml

  cargo_c_bin=""
  for cargo_c_dir in "${CARGO_TARGET_DIR:-}" "${PKG_BUILD}/.${RUST_HOST}/target" "${PKG_BUILD}/target"; do
    [ -n "${cargo_c_dir}" ] || continue
    if [ -x "${cargo_c_dir}/release/cargo-c" ]; then
      cargo_c_bin="${cargo_c_dir}/release/cargo-c"
      break
    fi
  done
  if [ -z "${cargo_c_bin}" ]; then
    echo "ERROR: cargo-c binary not found after the host build" >&2
    return 1
  fi

  mkdir -p ${TOOLCHAIN}/bin
  cp -a "${cargo_c_bin}" ${TOOLCHAIN}/bin/
  if [ -n "${CARGO_HOME}" ]; then
    mkdir -p "${CARGO_HOME}/bin"
    cp -a "${cargo_c_bin}" "${CARGO_HOME}/bin/"
  fi
}
