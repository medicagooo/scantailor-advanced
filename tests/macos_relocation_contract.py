"""Offline Mach-O graph tests; fake tool outputs, real filesystem copies."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import relocate_macos as deploy


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.bundle = self.root / 'ScanTailor Advanced.app'
        self.binary = self.bundle / 'Contents/MacOS/scantailor-advanced'
        self.definitions = {}
        self.state = {}
        self.create(self.binary, 'app', [])

    def tearDown(self):
        self.temp.cleanup()

    def create(self, path, key, deps, paths=(), library=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes.fromhex('cffaedfe') + key.encode())
        self.definitions[key] = {'deps': list(deps), 'rpaths': list(paths), 'ids': [str(path)] if library else []}
        return path

    def tool(self, *args):
        if args[0] == 'otool':
            name = args[2]
        elif args[0] == 'lipo':
            self.assertEqual(args[2:], ('-verify_arch', 'arm64'))
            return ''
        else:
            self.assertEqual(args[0], 'install_name_tool')
            name = args[-1]
        key = Path(name).read_bytes()[4:].decode()
        state = self.state.setdefault(name, copy.deepcopy(self.definitions[key]))
        if args[:2] == ('otool', '-L'):
            return name + ':\n' + ''.join(f'\t{x} (compatibility version 1.0.0, current version 1.0.0)\n' for x in state['ids'] + state['deps'])
        if args[:2] == ('otool', '-D'):
            return name + ':\n' + '\n'.join(state['ids'])
        if args[:2] == ('otool', '-l'):
            return ''.join(f'cmd LC_RPATH\ncmdsize 40\npath {x} (offset 12)\n' for x in state['rpaths'])
        if args[1] == '-change':
            state['deps'] = [args[3] if d == args[2] else d for d in state['deps']]
        elif args[1] == '-delete_rpath':
            state['rpaths'].remove(args[2])
        elif args[1] == '-id':
            state['ids'] = [args[2]]
        else:
            self.fail(str(args))
        return ''

    def test_recursive_dependencies_and_space_paths(self):
        libs = self.root / 'brew libraries'
        b = self.create(libs / 'libb.dylib', 'b', ['/usr/lib/libSystem.B.dylib'], library=True)
        a = self.create(libs / 'liba.dylib', 'a', [str(b)], library=True)
        self.definitions['app']['deps'] = ['@rpath/liba.dylib']
        self.definitions['app']['rpaths'] = [str(libs)]
        with patch.object(deploy, 'run', self.tool):
            deploy.relocate(self.bundle, 'arm64')
        self.assertTrue((self.bundle / 'Contents/Frameworks/libb.dylib').is_file())
        self.assertEqual(self.state[str(self.binary)]['deps'], ['@loader_path/../Frameworks/liba.dylib'])
        self.assertEqual(self.state[str(self.binary)]['rpaths'], [])

    def test_missing_dependency_rejected(self):
        self.definitions['app']['deps'] = ['@rpath/missing.dylib']
        with patch.object(deploy, 'run', self.tool), self.assertRaisesRegex(RuntimeError, 'Unresolved'):
            deploy.relocate(self.bundle, 'arm64')

    def test_deployed_library_missing_transitive_peer(self):
        libs = self.root / 'brew libraries'
        self.create(libs / 'libsharpyuv.0.dylib', 'yuv', ['/usr/lib/libSystem.B.dylib'], library=True)
        self.create(self.bundle / 'Contents/Frameworks/libwebp.7.dylib', 'webp',
                    ['@rpath/libsharpyuv.0.dylib'], library=True)
        self.definitions['app']['deps'] = ['@rpath/libwebp.7.dylib']
        with patch.object(deploy, 'run', self.tool):
            deploy.relocate(self.bundle, 'arm64', [libs])
        peer = self.bundle / 'Contents/Frameworks/libsharpyuv.0.dylib'
        self.assertTrue(peer.is_file())
        webp = str(self.bundle / 'Contents/Frameworks/libwebp.7.dylib')
        self.assertEqual(self.state[webp]['deps'], ['@loader_path/libsharpyuv.0.dylib'])

    def test_external_framework_rejected(self):
        lib = self.create(self.root / 'QtCore.framework/Versions/A/QtCore', 'qt', [], library=True)
        self.definitions['app']['deps'] = [str(lib)]
        with patch.object(deploy, 'run', self.tool), self.assertRaisesRegex(RuntimeError, 'external framework'):
            deploy.relocate(self.bundle, 'arm64')

    def test_conflicting_library_names_rejected(self):
        a = self.create(self.root / 'one/libx.dylib', 'one', [], library=True)
        b = self.create(self.root / 'two/libx.dylib', 'two', [], library=True)
        self.definitions['app']['deps'] = [str(a), str(b)]
        with patch.object(deploy, 'run', self.tool), self.assertRaisesRegex(RuntimeError, 'collision'):
            deploy.relocate(self.bundle, 'arm64')

    def test_relative_reference_must_resolve_inside_bundle(self):
        self.assertFalse(deploy.inside(self.bundle / '../escape', self.bundle))
        self.assertTrue(deploy.inside(self.bundle / 'Contents', self.bundle))
        self.assertFalse(deploy.system_path('/usr/local/lib/a.dylib'))
        self.assertTrue(deploy.system_path('/usr/lib/libSystem.B.dylib'))


if __name__ == '__main__':
    unittest.main()
