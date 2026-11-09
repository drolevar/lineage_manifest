# BLA-L29: LineageOS 24.0 source preparation

**Status: preparation only. Not build-ready or boot-ready.** This branch prepares
an experimental Android 17 / LineageOS 24.0 port for the Huawei Mate 10 Pro
(`blanc`). A source sync, compile, device boot and `.225` proprietary extraction
have not been validated by this preparation. The starting device trees came from
`lineage-22.2`; their dependency and platform compatibility audit is still work
to do. See [the compatibility notes](compatibility-notes.md) for the initial
assessment and remaining evidence gaps.

The reported device baseline is unlocked EMUI 12 .225 (complete stock build
identifier pending) with working TWRP.
That is not a measurement of its Android API, kernel, partition map or encryption
compatibility. This guide performs no device operations.

## What is pinned

[`source-plan.json`](source-plan.json) is the machine-readable source plan:

| Source | Selection |
| --- | --- |
| Preparation files | `drolevar/lineage_manifest`, `blanc-lineage-24.0` |
| Upstream manifest content | Exact commit `b51a0c449a3279ca55fb6d4d91d2143e42e2fff5` from `lineage-24.0` |
| Four Huawei projects | Exact commit per project, with `blanc-lineage-24.0` as the upstream branch hint |
| Original device-project bases | Recorded separately as `base_commit`, for provenance |
| Proprietary vendor files | Pending extraction from the device's exact firmware; no vendor repository is assumed |

The preparation branch contains this guide and tooling. **The Android source
checkout deliberately initializes at the pinned upstream manifest base**, then
adds a separate local manifest for the four Huawei forks. It does not initialize
at the moving preparation branch, modify upstream `default.xml`, or require a
self-referential manifest commit pin.

Pinning a manifest commit does **not** pin all Android project revisions: the
upstream XML still contains branch references. A complete resolved lock requires
a successful full sync followed by `repo manifest -r`. The four device commits
are pinned immediately. A `PENDING_*` value is an unresolved pin; the checker
rejects it before any initialization.

[`blanc-pinned.xml`](blanc-pinned.xml) is the generated, reviewable copy of the
device overlay. `source-plan.json` is its only editable source; the checker and
tests verify exact agreement. After an intentional pin change, regenerate it:

```sh
python3 huawei/bootstrap.py render > huawei/blanc-pinned.xml
python3 huawei/bootstrap.py check
```

The XML can be inspected or copied to `.repo/local_manifests/blanc-pinned.xml`
in a checkout initialized at the exact manifest base. The `overlay` command
performs the checks described below before writing the same bytes.

The pinned upstream `snippets/lineage.xml` already includes the legacy inline
kernel compiler at `prebuilts/clang/kernel/linux-x86/clang-r416183b`, from
`LineageOS/android_prebuilts_clang_kernel_linux-x86_clang-r416183b` on
`lineage-20.0`. Do not add a duplicate project to obtain it. Its suitability for
the migrated kernel still needs validation, and its exact commit will be recorded
by the full resolved source lock.

## Prerequisites

Use Linux with Python 3.10 or newer, Git, Git LFS and Android's `repo` tool.
Provide storage and network access appropriate for a full Android source tree
when you choose to sync it. The bootstrap does not install software or download
the Android source tree.

Keep this small preparation checkout separate from the large Android checkout.
For example, inside your existing `~/projects/huawei` workspace:

```sh
git clone --branch blanc-lineage-24.0 https://github.com/drolevar/lineage_manifest.git lineage-preparation
cd lineage-preparation
python3 huawei/bootstrap.py check
```

`check` validates the plan, upstream XML checksum and generated overlay, and
reports locally available tools as JSON. A zero exit status means the **plan
format, pins and generated copy** are valid. It is not a build test,
remote commit-availability check or validation of the device trees.

## Initialize a separate checkout

Review the source plan first. Then explicitly initialize a **new or empty**
directory:

```sh
python3 huawei/bootstrap.py init --source "$HOME/projects/huawei/src/lineage-24.0"
```

This runs only:

1. `repo init` against the configured fork at the exact upstream base commit,
   with Git LFS enabled.
2. Verification of the manifest HEAD, clean manifest worktree and `default.xml`
   checksum.
3. Creation of `.repo/local_manifests/blanc-pinned.xml`, containing four exact
   project revisions.

`repo init` uses the network for its own tooling and manifest metadata. **No
`repo sync`, build, phone access, partition write or firmware download is run.**
If initialization fails, its partial directory is retained for inspection. The
tool will not wipe it or silently reset it on retry.

For an independently initialized checkout already at the exact manifest base:

```sh
python3 huawei/bootstrap.py overlay --source "$HOME/projects/huawei/src/lineage-24.0"
```

The overlay operation is idempotent when the existing file matches. It refuses
to overwrite a different overlay, operate on a dirty/different manifest checkout,
or combine the overlay with other local XML manifests without review. It changes
no checked-out device or platform source files.

## Full sync is a separate, deliberate step

Once the repository plan and download size have been reviewed, run the sync
yourself in the new checkout. Start with conservative parallelism:

```sh
cd "$HOME/projects/huawei/src/lineage-24.0"
repo sync -c -j4
```

Do not add `--force-sync`, `--force-checkout`, `git reset --hard`, or missing-
dependency overrides to hide a failure. Preserve the first error and investigate
the project it identifies. In particular, do not enable
`ALLOW_MISSING_DEPENDENCIES` to call the migration complete.

After a successful sync, run the audit using the tool from the preparation clone:

```sh
python3 "$HOME/projects/huawei/lineage-preparation/huawei/bootstrap.py" audit --source "$HOME/projects/huawei/src/lineage-24.0"
```

`audit` checks the pinned manifest and overlay, presence of every listed project,
the four pinned device heads, and tracked/untracked changes across the repo
checkout. It performs no reset or sync. A clean audit still does not establish
that inherited makefiles, Soong modules, kernel configurations or HAL interfaces
are compatible with Android 17.

Before later syncs, run the audit and preserve intentional work in commits. If
device heads or local manifests are intentionally changed, update the source
plan deliberately instead of forcing the checker to accept an unexplained state.

## Record a complete source lock after sync

From the Android source root, save the resolved manifest outside that source tree:

```sh
repo manifest -r -o "$HOME/projects/huawei/lineage-24.0-resolved.xml"
sha256sum "$HOME/projects/huawei/lineage-24.0-resolved.xml"
```

Keep the resolved XML, its hash, the preparation branch commit, tool versions and
the source plan together in the project record. This is the first complete
platform revision lock. Review the lock before committing or publishing it,
especially if additional private remotes were added. Regenerate it only for an
intentional source update; keep previous locks.

## Next engineering work

1. Audit device/common/hardware/kernel build dependencies against the pinned
   LineageOS 24 manifest; record every compatibility patch and its origin.
2. Capture current Android properties, kernel/config, real partition map and boot
   image formats separately from recovery data. Preserve the working TWRP route.
3. Extract the exact `.225` hardware dependencies, including their mounted
   overlay sources, privately with hashes and firmware provenance. Do not reuse
   an unrelated vendor bundle to satisfy a missing makefile.
4. Prove a source-built BLA kernel and the minimal Android 17 userspace path, then
   tackle hardware, encryption, enforcing policy and install/update integration.

An existing LineageOS 22.2 source sync is useful history, but is not evidence that
this LineageOS 24 source set has synced or built. No build product or working ROM
is claimed by this branch.

## Tool tests

The tests use temporary local Git repositories, never the network or a device:

```sh
python3 -m unittest discover -s huawei/tests -v
```

They exercise unresolved pins, conflicting paths/manifests, preserving existing
directories and modified work, idempotent creation of the pinned overlay, and
agreement between the checked-in generated XML and its JSON source.
