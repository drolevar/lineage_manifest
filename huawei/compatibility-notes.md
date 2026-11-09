# Source selection and compatibility notes

Reviewed on 2026-11-09 for the BLA-L29 LineageOS 24 preparation. These are
source findings and implementation decisions, not device test results.

## Repository decisions

The existing `drolevar` repositories already provide the necessary maintenance
boundaries. The new `blanc-lineage-24.0` branches retain the previous device,
common, hardware, and kernel history; no duplicate fork network is needed.

| Component | Selected base and purpose |
| --- | --- |
| Manifest | `LineageOS/android` descendant; upstream Lineage 24 content plus separate pinned Huawei overlay |
| Blanc | Existing BLA adaptation of the Berkeley Gerrit tree; BLA-specific configuration and extraction metadata belong here |
| Kirin 970 common | Existing Lineage Gerrit stack; shared platform configuration and proven compatibility selections |
| Huawei hardware | Existing Lineage Gerrit stack; shared HAL/init/policy and split-image packaging |
| Kernel | Existing `hisi-oss` fork; preserve maintained kernel/backport history |
| Berkeley / Charlotte | Reference trees only; not additional device projects in this product manifest |
| Proprietary vendor | Generate from an audited BLA `.225` extraction; do not create a public dump repository to fill missing inputs |
| Frameworks and system | Use the selected upstream source until a reproducible compatibility failure justifies a focused patch or fork |

The exact project bases and preparation heads are recorded in
[`source-plan.json`](source-plan.json). GitHub fork ancestry was checked for the
manifest, common, hardware and kernel repositories. Blanc is a separate
repository that preserves its donor Git history.

## Kernel source identity

Huawei's supplied archive is **BLA-AL00B EMUI 10.0**, Linux **4.14.116**:

```text
BLA-AL00B_10_EMUI10.0_opensource.tar.gz
size:   548702193 bytes
sha256: af91156db6d6ebff38c1ca3efcaf9de25db754324648032d4aadc1aa9b6308c0
```

It is a comparison and reproduction reference. It is not labeled as source for
the installed BLA-L29 EMUI 12 `.225` kernel. The maintained development fork is
not byte-identical to this release: selected reserved-memory definitions and
conditional partition tables differ even though inspected SoC base-address and
UFS register definitions match. Neither source table establishes the live GPT.

The kernel repository's `Documentation/huawei/` records the official download,
hashes, comparison, and reference-build recipe. That recipe uses the official
source's **Clang r346389c plus GCC 4.9 cross tools and GNU gold/LLVMgold**, as
required by its actual Makefile. The short Huawei README alone omits that Clang
requirement.

The selected development common tree instead uses **Clang r416183b**,
`merge_kirin970_defconfig`, and `TARGET_KERNEL_LLVM_BINUTILS := false`.
Upstream Lineage 24's `snippets/lineage.xml` already supplies the r416183b
prebuilt project. Its actual commit, kernel build tools, userspace compiler,
and all other platform projects must be captured in the full resolved manifest
after sync. Do not substitute the stock compiler into the maintained fork, or
the maintained fork's compiler into stock reproduction, without a separate test.

## Verified compatibility mechanisms

| Topic | Source finding | Preparation decision |
| --- | --- | --- |
| Gralloc | Lineage 24 retains a typed `libui.legacy_gralloc` Soong switch and a Gralloc2/3 fallback | Enable it for the declared mapper 2.1 stack. This records intent; it is not a demonstrated boot fix. |
| BPF | The loader has a kernel-version override and feature/version requirements | Audit the complete backport set and kernel configuration. Changing the advertised version does not implement features. |
| Capabilities / zygote | Capability probing and the selected zygote implementation determine the required kernel behavior | Do not change `CAP_LAST_CAP` alone and call newer capability semantics implemented. |
| Encryption | The fscrypt library still distinguishes policy v1/v2 and selects defaults using first API level | Policy version, kernel key-management ioctls, vendor keymaster and vold behavior require separate checks. No blanket v2 conversion. |
| Legacy HALs | Audio HIDL v5 and thermal v1 implementation modules remain in the inspected Lineage 24 source | Module age alone is not a reason to fork all of hardware/interfaces. Framework support, VINTF and binary ABI remain separate questions. |
| Boot packaging | The selected Huawei hardware tree has its own split-image rules | Inspect those rules and actual images; do not transplant an old recovery-only dummy-kernel recipe. |

The gralloc option is:

```make
$(call soong_config_set_bool,libui,legacy_gralloc,true)
```

The selected code normally requires mapper 4 only under additional API/feature
conditions. This switch does not solve ION device access, SELinux, Mali symbols,
buffer layout, or hardware composer integration.

Primary source references:

- [libui build configuration](https://github.com/LineageOS/android_frameworks_native/blob/lineage-24.0/libs/ui/Android.bp)
  and [GraphicBufferMapper](https://github.com/LineageOS/android_frameworks_native/blob/lineage-24.0/libs/ui/GraphicBufferMapper.cpp).
- [Connectivity kernel helpers](https://github.com/LineageOS/android_packages_modules_Connectivity/blob/lineage-24.0/bpf/headers/include/bpf/KernelUtils.h)
  and [system BPF loader](https://github.com/LineageOS/android_system_bpf/blob/lineage-24.0/loader/bpfloader.rs).
- [Zygote capability handling](https://github.com/LineageOS/android_frameworks_base/blob/lineage-24.0/core/jni/com_android_internal_os_Zygote.cpp).
- [fscrypt policy handling](https://github.com/LineageOS/android_system_extras/blob/lineage-24.0/libfscrypt/fscrypt.cpp).
- [Audio implementation modules](https://github.com/LineageOS/android_hardware_interfaces/blob/lineage-24.0/audio/core/all-versions/default/Android.bp)
  and [thermal implementation modules](https://github.com/LineageOS/android_hardware_interfaces/blob/lineage-24.0/thermal/1.0/default/Android.bp).

These branch links identify the inspected implementation; the eventual resolved
source lock, rather than a moving branch URL, must identify a tested build.

## Unresolved port work

The Blanc donor tree still contains a Berkeley-derived super size, BKL camera
service arguments and BKL/BKLY/BERK extraction entries. The common fstab also
assigns the physical `patch` partition to `/metadata` with a formatting flag.
No such value or behavior is validated for the current handset by this source
preparation. Review the stock `.225` and working-recovery captures first.

The inherited common and supplemental vendor framework manifests use **FCM
level 5**. They must be reconciled with the selected platform; relabeling an old
vendor as a newer FCM level is not an implementation of its requirements. The
inspected device/common source does not itself establish an exact vendor VNDK
version; determine the dependencies from firmware and generated vendor inputs.

The earlier 22.2 audio framework, `libui-v29`, `libjsoncpp-v30`, and binary-XML
extraction patches need a new applicability and dependency audit. They are not
silently applied to 24. Record any necessary rebased patch with its upstream
origin and the exact source revision it changes before adding another fork.

Only after that source and firmware work should the build be configured with:

```sh
source build/envsetup.sh
breakfast blanc userdebug
```

Lineage's [breakfast implementation](https://github.com/LineageOS/android_vendor_lineage/blob/lineage-24.0/build/envsetup.sh)
selects the release token from the checked-out branch. Do not copy a two-field
lunch target or assume a release token from another Android branch.

Hardware functionality, encryption, enforcing policy, install/update behavior,
and official LineageOS charter compliance remain untested. A source tree or a
list of HAL filenames is not evidence that those tests pass.
