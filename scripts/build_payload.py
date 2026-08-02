#!/usr/bin/env python3
"""Build Reefy's two NVIDIA SquashFS payload layers from pinned inputs."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VERSIONS = json.loads((ROOT / 'versions.json').read_text())
DRIVER = VERSIONS['nvidia_driver']


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_executable(source, destination):
    """Copy a host tool without trusting transport-preserved mode bits.

    GitHub Actions artifact upload/download preserves file contents but
    normalizes regular-file permissions. Provider inputs therefore arrive as
    0644 even though Buildroot staged them as executables.
    """
    copy(source, destination)
    destination.chmod(0o755)


def replace_symlink(destination, target):
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.unlink()
    except FileNotFoundError:
        pass
    destination.symlink_to(target)


def extract_installer(installer, work):
    if installer.stat().st_size != DRIVER['installer_bytes']:
        raise SystemExit('NVIDIA installer size mismatch')
    if sha256(installer) != DRIVER['installer_sha256']:
        raise SystemExit('NVIDIA installer SHA-256 mismatch')
    subprocess.run(
        [str(installer), '--extract-only'], cwd=work, check=True)
    candidates = list(work.glob(
        f'NVIDIA-Linux-x86_64-{DRIVER["version"]}'))
    if len(candidates) != 1:
        raise SystemExit('NVIDIA installer extraction layout changed')
    return candidates[0]


def stage_common(extracted, toolkit_dir, root):
    library_dir = root / 'usr/lib'
    manifest = extracted / '.manifest'
    for raw in manifest.read_text().splitlines():
        fields = raw.split()
        if len(fields) < 4 or fields[3] != 'NATIVE':
            continue
        name, mode, kind = fields[:3]
        if mode != '0000' and 'LIB' in kind:
            source = extracted / name
            if source.is_file():
                copy(source, library_dir / Path(name).name)
        elif (mode == '0000' and 'SYMLINK' in kind
              and kind not in ('SYSTEMD_UNIT_SYMLINK',
                               'UTILITY_BIN_SYMLINK')):
            values = [
                value for value in fields[4:]
                if value != '/' and not value.startswith('MODULE:')]
            if values:
                replace_symlink(
                    library_dir / Path(name).name,
                    Path(values[-1]).name)

    ngx_library = library_dir / f'libnvidia-ngx.so.{DRIVER["version"]}'
    if not ngx_library.is_file():
        raise SystemExit('NVIDIA installer has no native NGX library')
    replace_symlink(
        library_dir / 'libnvidia-ngx.so.1', ngx_library.name)
    replace_symlink(
        library_dir / 'libnvidia-ngx.so', 'libnvidia-ngx.so.1')

    copy_executable(extracted / 'nvidia-smi', root / 'usr/bin/nvidia-smi')
    copy_executable(
        extracted / 'nvidia-ngx-updater',
        root / 'usr/bin/nvidia-ngx-updater')
    for binary in ('nvidia-ctk', 'nvidia-cdi-hook'):
        source = toolkit_dir / binary
        if not source.is_file():
            raise SystemExit(f'missing NVIDIA Container Toolkit binary: {source}')
        copy_executable(source, root / 'usr/bin' / binary)

    copy(
        extracted / 'nvidia_icd.json',
        root / 'usr/share/vulkan/icd.d/nvidia_icd.json')
    copy(
        extracted / '10_nvidia.json',
        root / 'usr/share/glvnd/egl_vendor.d/10_nvidia.json')
    copy(
        extracted / 'nvidia_layers.json',
        root / 'usr/share/vulkan/implicit_layer.d/nvidia_layers.json')
    for name in (
            '09_nvidia_wayland2.json',
            '10_nvidia_wayland.json',
            '15_nvidia_gbm.json',
            '20_nvidia_xcb.json',
            '20_nvidia_xlib.json'):
        copy(
            extracted / name,
            root / 'usr/share/egl/egl_external_platform.d' / name)
    for name in (
            f'nvidia-application-profiles-{DRIVER["version"]}-rc',
            f'nvidia-application-profiles-{DRIVER["version"]}-key-documentation',
            'nvoptix.bin'):
        copy(extracted / name, root / 'usr/share/nvidia' / name)
    copy(
        extracted / 'sandboxutils-filelist.json',
        root / 'usr/share/nvidia/files.d/sandboxutils-filelist.json')
    for source in sorted((extracted / 'firmware').glob('gsp_*.bin')):
        copy(
            source,
            root / 'lib/firmware/nvidia' / DRIVER['version'] / source.name)
    firmware = sorted(
        (root / 'lib/firmware/nvidia' / DRIVER['version']).glob('gsp_*.bin'))
    if len(firmware) < 2:
        raise SystemExit('NVIDIA installer has no complete GSP firmware set')
    copy(
        extracted / 'LICENSE',
        root / 'usr/share/licenses/nvidia-driver/LICENSE')


def stage_kernel(modules_dir, kernel_release, root):
    destination = root / 'lib/modules' / kernel_release / 'extra/nvidia'
    modules = sorted(modules_dir.rglob('nvidia*.ko*'))
    if not modules:
        raise SystemExit(f'no NVIDIA modules found under {modules_dir}')
    for source in modules:
        copy(source, destination / source.name)
    required = {'nvidia', 'nvidia-drm', 'nvidia-modeset', 'nvidia-uvm'}
    present = {
        path.name.split('.ko', 1)[0] for path in destination.iterdir()
    }
    missing = required - present
    if missing:
        raise SystemExit(
            'missing required NVIDIA modules: ' + ', '.join(sorted(missing)))


def squash(source, destination):
    subprocess.run([
        'mksquashfs', str(source), str(destination),
        '-noappend', '-comp', 'xz', '-b', '1M', '-Xdict-size', '1M',
        '-all-root', '-all-time', '0', '-mkfs-time', '0', '-no-xattrs',
        '-no-progress',
    ], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--modules-dir', type=Path, required=True)
    parser.add_argument('--toolkit-dir', type=Path, required=True)
    parser.add_argument('--kernel-release', required=True)
    parser.add_argument('--reefy-build-id', required=True)
    parser.add_argument('--kernel-abi-digest', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='reefy-nvidia-') as temporary:
        extracted = extract_installer(args.installer.resolve(), Path(temporary))
        common = args.output / 'common-root'
        kernel = args.output / 'kernel-root'
        shutil.rmtree(common, ignore_errors=True)
        shutil.rmtree(kernel, ignore_errors=True)
        stage_common(extracted, args.toolkit_dir.resolve(), common)
        stage_kernel(
            args.modules_dir.resolve(), args.kernel_release, kernel)
        squash(common, args.output / 'common.squashfs')
        squash(kernel, args.output / 'kernel.squashfs')

    config = {
        'artifact_schema': 1,
        'kind': 'host-extension',
        'name': 'nvidia-driver',
        'version': DRIVER['version'],
        'nvidia_container_toolkit_version':
            VERSIONS['nvidia_container_toolkit']['version'],
        'architecture': 'x86_64',
        'publisher': 'reefyai',
        'reefy_build_id': args.reefy_build_id,
        'kernel_abi_digest': args.kernel_abi_digest,
    }
    (args.output / 'config.json').write_text(
        json.dumps(config, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
