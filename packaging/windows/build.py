"""Build the Windows RacePlan.exe folder and its zip (run from the repository root on Windows x64):

    uv run --locked --extra exe python packaging/windows/build.py

Steps: PyInstaller (packaging/windows/RacePlan.spec) into dist/RacePlan, then the demo scenarios, maps, example
planner, Windows guide and third-party licenses next to RacePlan.exe, then a check that every RacePlan source file in
the bundle is byte-identical to the checkout (provenance records their sha256), then
dist/RacePlan-<version>-windows-x64.zip with its .sha256. Any mismatch stops the build. BUILD-INFO.txt records the
commit and tool versions. Only CPython 3.13 64-bit on Windows x64 is accepted.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / 'dist'
APP = DIST / 'RacePlan'
SHIPPED = ['scenarios/demo.yaml', 'scenarios/validation_open.yaml', 'maps/demo.yaml', 'maps/demo.pgm',
           'maps/validation_open.yaml', 'maps/validation_open.pgm', 'maps/README.md', 'examples/my_planner.py']
THIRD_PARTY = ['numpy', 'pillow', 'pyyaml', 'pyinstaller']


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources(folder):
    return {path.relative_to(folder).as_posix(): _sha256(path)
            for path in folder.rglob('*.py') if '__pycache__' not in path.parts}


def check_sources(app):
    """The bundle must carry exactly the checkout's RacePlan .py files, byte for byte."""
    expected, packaged = _sources(ROOT / 'src' / 'raceplan'), _sources(app / '_internal' / 'raceplan')
    missing = sorted(set(expected) - set(packaged))
    extra = sorted(set(packaged) - set(expected))
    changed = sorted(name for name in set(expected) & set(packaged) if expected[name] != packaged[name])
    if missing or extra or changed:
        raise SystemExit(f'packaged RacePlan sources differ from the checkout: missing={missing} extra={extra} '
                         f'changed={changed}')
    if not (app / '_internal' / 'raceplan' / 'gui' / 'static' / 'index.html').is_file():
        raise SystemExit('the explorer page (raceplan/gui/static/index.html) is missing from the bundle')
    return len(expected)


def copy_licenses(app):
    """Every license file the bundled distributions ship (their .dist-info/licenses tree), and Python's. A missing
    notice stops the build. RacePlan's own notice comes from LICENSE in the repository when there is one."""
    folder = app / 'licenses'
    folder.mkdir()
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise SystemExit(f'Python license notice not found: {python_license}')
    (folder / 'Python').mkdir()
    shutil.copyfile(python_license, folder / 'Python' / 'LICENSE.txt')
    for name in THIRD_PARTY:
        distribution = importlib.metadata.distribution(name)
        files = [file for file in distribution.files or [] if len(file.parts) > 2 and file.parts[1] == 'licenses']
        if not files:
            raise SystemExit(f'no license files found for {name}')
        for file in files:
            target = folder / distribution.metadata['Name'] / Path(*file.parts[2:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file.locate(), target)
    own = ROOT / 'LICENSE'
    if own.is_file():
        shutil.copyfile(own, folder / 'RacePlan-LICENSE.txt')
        return None
    return 'the repository has no LICENSE file, so RacePlan\'s own license notice is not included'


def check_target():
    """The zip is named windows-x64 and documented for CPython 3.13: refuse to build anything else."""
    if sys.platform != 'win32' or platform.machine().upper() not in ('AMD64', 'X86_64') or sys.maxsize <= 2**32:
        raise SystemExit(f'RacePlan.exe is built with 64-bit Python on Windows x64 (this is {sys.platform} '
                         f'{platform.machine()}, {"64" if sys.maxsize > 2**32 else "32"}-bit)')
    if sys.version_info[:2] != (3, 13):
        raise SystemExit(f'RacePlan.exe is built with CPython 3.13 (this is {platform.python_version()})')


def build_info(app, version, warning):
    def run(*command):
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    commit = run('git', 'rev-parse', 'HEAD') or 'unknown'
    dirty = ' (with uncommitted changes)' if run('git', 'status', '--porcelain', '--untracked-files=no') else ''
    lines = [f'RacePlan {version} for Windows x64', f'commit {commit}{dirty}', f'Python {platform.python_version()}',
             *(f'{name} {importlib.metadata.version(name)}' for name in THIRD_PARTY)]
    if warning:
        lines.append(f'note: {warning}')
    (app / 'BUILD-INFO.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    check_target()
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--distpath', str(DIST),
                    '--workpath', str(ROOT / 'build' / 'pyinstaller'), str(ROOT / 'packaging' / 'windows' / 'RacePlan.spec')],
                   cwd=ROOT, check=True)
    for name in SHIPPED:
        target = APP / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    shutil.copyfile(ROOT / 'docs' / 'WINDOWS_EXE.md', APP / 'README-Windows.md')
    warning = copy_licenses(APP)
    build_info(APP, version, warning)
    count = check_sources(APP)
    if warning:
        print(f'WARNING: {warning}')
    archive = DIST / f'RacePlan-{version}-windows-x64.zip'
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(APP.rglob('*')):
            if path.is_file():
                bundle.write(path, Path('RacePlan') / path.relative_to(APP))
    digest = _sha256(archive)
    (DIST / f'{archive.name}.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    size = sum(path.stat().st_size for path in APP.rglob('*') if path.is_file())
    print(f'RacePlan sources checked: {count} files identical to the checkout')
    print(f'folder {APP} ({size / 2**20:.1f} MiB)')
    print(f'zip    {archive} ({archive.stat().st_size / 2**20:.1f} MiB) sha256 {digest}')


if __name__ == '__main__':
    main()
