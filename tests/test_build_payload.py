import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/build_payload.py'
SPEC = importlib.util.spec_from_file_location('nvidia_build_payload', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BuildPayloadTests(unittest.TestCase):
    def test_squashfs_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(MODULE.subprocess, 'run') as run:
            root = Path(temporary)
            MODULE.squash(root / 'source', root / 'payload.squashfs')

        command = run.call_args.args[0]
        self.assertIn('-mkfs-time', command)
        self.assertIn('-all-time', command)
        self.assertIn('-all-root', command)

    def test_stages_native_libraries_firmware_tools_and_license(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = root / 'extracted'
            toolkit = root / 'toolkit'
            output = root / 'output'
            extracted.mkdir()
            toolkit.mkdir()
            (extracted / 'firmware').mkdir()
            (extracted / '.manifest').write_text(
                'libcuda.so.595.84 0755 CUDA_LIB NATIVE / MODULE:gpgpu\n'
                'libcuda.so.1 0000 CUDA_SYMLINK NATIVE / '
                'libcuda.so.595.84 MODULE:gpgpu\n'
                './32/libcuda.so.595.84 0755 CUDA_LIB COMPAT32 / '
                'MODULE:gpgpu\n')
            (extracted / 'libcuda.so.595.84').write_bytes(b'cuda')
            (extracted / 'nvidia-smi').write_bytes(b'smi')
            (extracted / 'nvidia_icd.json').write_text('{}')
            (extracted / '10_nvidia.json').write_text('{}')
            (extracted / 'LICENSE').write_text('license')
            for name in ('gsp_tu10x.bin', 'gsp_ga10x.bin'):
                (extracted / 'firmware' / name).write_bytes(name.encode())
            for name in ('nvidia-ctk', 'nvidia-cdi-hook'):
                (toolkit / name).write_bytes(name.encode())

            MODULE.stage_common(extracted, toolkit, output)

            self.assertEqual(
                (output / 'usr/lib/libcuda.so.595.84').read_bytes(), b'cuda')
            self.assertEqual(
                (output / 'usr/lib/libcuda.so.1').readlink(),
                Path('libcuda.so.595.84'))
            self.assertFalse((output / 'usr/lib/32').exists())
            self.assertEqual(
                (output / 'usr/share/licenses/nvidia-driver/LICENSE').read_text(),
                'license')
            self.assertEqual(len(list(
                (output / 'lib/firmware/nvidia/595.84').glob('gsp_*.bin'))), 2)

    def test_kernel_stage_requires_complete_module_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            modules = root / 'modules'
            modules.mkdir()
            for name in ('nvidia', 'nvidia-drm', 'nvidia-modeset', 'nvidia-uvm'):
                (modules / f'{name}.ko.xz').write_bytes(name.encode())

            output = root / 'output'
            MODULE.stage_kernel(modules, '6.18.40', output)
            installed = output / 'lib/modules/6.18.40/extra/nvidia'
            self.assertEqual(len(list(installed.glob('nvidia*.ko.xz'))), 4)

            (modules / 'nvidia-uvm.ko.xz').unlink()
            with self.assertRaises(SystemExit):
                MODULE.stage_kernel(modules, '6.18.41', root / 'incomplete')


if __name__ == '__main__':
    unittest.main()
