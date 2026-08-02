# Reefy NVIDIA provider

Reproducible host-extension payloads for NVIDIA GPUs on Reefy OS.

One published OCI manifest contains two SquashFS layers:

- `common.squashfs`: matching GSP firmware, NVIDIA host userspace, Vulkan,
  EGL/GLVND metadata, `nvidia-smi`, and NVIDIA Container Toolkit binaries;
- `kernel.squashfs`: open NVIDIA modules built by the exact Reefy kernel and
  toolchain identified in artifact metadata.

The common payload includes the provider-owned activation hook at the fixed
path `usr/lib/reefy/activate`. Reefy verifies and mounts the digest-pinned
payload before invoking that hook. The hook lets the loaded NVIDIA driver
determine whether usable hardware is present, activates the matched modules,
firmware and userspace, and atomically publishes CDI only after successful
initialization. Application images continue supplying CUDA runtime
frameworks, TensorRT, PyTorch, Isaac Sim, and other app-specific libraries.

The proprietary files are redistributed unchanged under section 1.1(d) of
the NVIDIA Driver License Agreement. A copy of that agreement is included in
every common payload.

## Version policy

The production target is NVIDIA R595 Production Branch `595.84`. Kernel
modules, GSP firmware, and userspace must always use the same release. The
exact upstream URLs, source commit, sizes, and SHA-256 hashes are pinned in
[`versions.json`](versions.json).

## Build

The publish workflow takes a Reefy source revision plus the immutable Reefy
build ID and kernel ABI digest. Reefy's firmware workflow builds the modules
and NVIDIA Container Toolkit with the exact Buildroot toolchain, then invokes
this repository's reusable workflow. The provider workflow creates an SBOM,
pushes a digest-addressed manifest to `ghcr.io/reefyai/reefy-nvidia`, and signs
it through GitHub OIDC.

Mutable tags are for discovery only. Reefy desired state always uses the
resolved manifest digest.
