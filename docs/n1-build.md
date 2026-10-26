# Building N1

Use the **N1 CoreELEC 21.3** Actions workflow, target `image`. Runs are manual;
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
experimental DV code must remain separately identifiable.
