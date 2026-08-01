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
                library_dir.mkdir(parents=True, exist_ok=True)
                link = library_dir / Path(name).name
                try:
                    link.unlink()
                except FileNotFoundError:
                    pass
                link.symlink_to(Path(values[-1]).name)

    copy(extracted / 'nvidia-smi', root / 'usr/bin/nvidia-smi')
    for binary in ('nvidia-ctk', 'nvidia-cdi-hook'):
        source = toolkit_dir / binary
        if not source.is_file():
            raise SystemExit(f'missing NVIDIA Container Toolkit binary: {source}')
        copy(source, root / 'usr/bin' / binary)

    copy(
        extracted / 'nvidia_icd.json',
        root / 'usr/share/vulkan/icd.d/nvidia_icd.json')
    copy(
        extracted / '10_nvidia.json',
        root / 'usr/share/glvnd/egl_vendor.d/10_nvidia.json')
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
