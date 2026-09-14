"""Make a deployed app's Mach-O dependency closure relocatable, then audit it.

Called only by Package-MacOS.ps1 after macdeployqt. Non-Qt dylibs are copied
recursively; Qt frameworks must already be deployed by Qt's tool. Every load
reference becomes bundle-local or an Apple system library before signing.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

MAGIC = {bytes.fromhex(x) for x in ('feedface', 'cefaedfe', 'feedfacf', 'cffaedfe', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}


def run(*args):
    return subprocess.check_output(args, text=True, encoding='utf-8', stderr=subprocess.STDOUT)


def is_macho(path):
    with path.open('rb') as stream:
        return stream.read(4) in MAGIC


def dependencies(output):
    return [m.group(1) for line in output.splitlines()
            if (m := re.match(r'\s+(.+?) \(compatibility version ', line))]


def rpaths(output):
    return re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset \d+\)', output)


def system_path(name):
    return name.startswith(('/usr/lib/', '/System/Library/'))


def inside(path, root):
    return path.resolve().is_relative_to(root.resolve())


def expand(name, binary, executable):
    if name.startswith('@loader_path/'):
        return binary.parent / name[len('@loader_path/'):]
    if name.startswith('@executable_path/'):
        return executable.parent / name[len('@executable_path/'):]
    if Path(name).is_absolute():
        return Path(name)
    return None


def locate(name, binary, executable, paths, frameworks):
    direct = expand(name, binary, executable)
    if direct is not None and direct.exists():
        return direct.resolve()
    if name.startswith('@rpath/'):
        suffix = name[len('@rpath/'):]
        for prefix in paths:
            folder = expand(prefix + '/', binary, executable)
            if folder is not None and (folder / suffix).exists():
                return (folder / suffix).resolve()
        # macdeployqt places frameworks here. References are rewritten below,
        # so this fallback does not depend on the original LC_RPATH surviving.
        if (frameworks / suffix).exists():
            return (frameworks / suffix).resolve()
    raise RuntimeError(f'Unresolved dependency {name} in {binary}')


def relocate(bundle, architecture):
    bundle = bundle.resolve()
    executable = bundle / 'Contents/MacOS/scantailor-advanced'
    frameworks = bundle / 'Contents/Frameworks'
    frameworks.mkdir(exist_ok=True)
    executable_paths = rpaths(run('otool', '-l', str(executable)))
    queue = sorted({p.resolve() for p in bundle.rglob('*') if p.is_file() and is_macho(p)})
    origins = {}
    completed = set()
    while queue:
        binary = queue.pop(0)
        if binary in completed:
            continue
        if not inside(binary, bundle):
            raise RuntimeError(f'Bundle symlink escapes its root: {binary}')
        completed.add(binary)
        # Homebrew libraries can be read-only; only the staged copy is writable.
        binary.chmod(binary.stat().st_mode | stat.S_IWUSR)
        run('lipo', str(binary), '-verify_arch', architecture)
        paths = rpaths(run('otool', '-l', str(binary)))
        ids = run('otool', '-D', str(binary)).splitlines()[1:]
        for name in dependencies(run('otool', '-L', str(binary))):
            if name in ids or system_path(name):
                continue
            source = locate(name, origins.get(binary, binary), executable,
                            paths + executable_paths, frameworks)
            target = source
            if not inside(source, bundle):
                if any(part.endswith('.framework') for part in source.parts):
                    raise RuntimeError(f'Qt deployment left an external framework: {source}')
                target = frameworks / source.name
                if target.exists() and origins.get(target) != source:
                    if target.read_bytes() != source.read_bytes():
                        raise RuntimeError(f'Dependency basename collision: {target}')
                if not target.exists():
                    shutil.copy2(source, target)
                origins[target] = source
                queue.append(target)
            relative = Path(os.path.relpath(target, binary.parent)).as_posix()
            run('install_name_tool', '-change', name, '@loader_path/' + relative, str(binary))
        # All load commands now use @loader_path. Remove build-machine rpaths.
        for path in set(paths):
            run('install_name_tool', '-delete_rpath', path, str(binary))
        if ids:
            run('install_name_tool', '-id', '@rpath/' + os.path.relpath(binary, frameworks), str(binary))
    # Audit actual rewritten files, not the intended mapping.
    for binary in completed:
        ids = run('otool', '-D', str(binary)).splitlines()[1:]
        for name in dependencies(run('otool', '-L', str(binary))):
            if name in ids or system_path(name):
                continue
            target = expand(name, binary, executable)
            if target is None or not target.is_file() or not inside(target, bundle):
                raise RuntimeError(f'Non-relocatable dependency {name} in {binary}')
    print(f'Audited {len(completed)} Mach-O files for {architecture}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--arch', choices=('arm64', 'x86_64'), required=True)
    args = parser.parse_args()
    relocate(args.bundle, args.arch)
