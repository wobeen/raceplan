# PyInstaller spec for the Windows RacePlan.exe (one folder). Build with packaging/windows/build.py, not directly.
#
# RacePlan's own modules are collected as their .py source files ('py' mode), not compiled into the archive: several
# modules record the sha256 of their own source files in provenance, so the packaged files must be the same bytes as
# the checkout (build.py checks this). Every RacePlan module is collected, also ones nothing imports statically.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]
# Standard library modules a user planner commonly imports even when RacePlan itself does not.
FOR_USER_PLANNERS = ['abc', 'array', 'bisect', 'collections', 'copy', 'csv', 'dataclasses', 'decimal', 'enum',
                     'fractions', 'functools', 'heapq', 'itertools', 'json', 'math', 'numbers', 'operator', 'queue',
                     'random', 'statistics', 'time', 'typing']

a = Analysis(
    [str(ROOT / 'packaging' / 'windows' / 'entry.py')],
    pathex=[str(ROOT / 'src')],
    hiddenimports=collect_submodules('raceplan') + FOR_USER_PLANNERS,
    datas=[(str(ROOT / 'src' / 'raceplan' / 'gui' / 'static'), 'raceplan/gui/static')],
    excludes=['tkinter', 'pytest', '_pytest'],
    module_collection_mode={'raceplan': 'py'},
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    # A frozen interpreter ignores PYTHON* environment variables: UTF-8 and unbuffered output are set here instead,
    # so worker logs reach the explorer as they are written and in one encoding (syntax: PyInstaller run-time options).
    [('X utf8', None, 'OPTION'), ('u', None, 'OPTION')],
    exclude_binaries=True,
    name='RacePlan',
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name='RacePlan', upx=False)
