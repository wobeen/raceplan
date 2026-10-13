"""Verify every saved unit and write a portable source/data ZIP with SHA-256 inventory."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile,ZIP_DEFLATED
from raceplan.research_engine import digest,dump

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--name',default='research_20261013')
a=parser.parse_args()
if Path(a.name).name!=a.name or a.name in {'.','..'}:parser.error('invalid run name')
raw=ROOT/'results/raw'/a.name
report=ROOT/'results/analysis'/a.name
completed=list(raw.glob('*/*/complete.json'))
if len(completed)!=29:raise ValueError(f'expected 29 complete units, got {len(completed)}')
for path in completed:
 record=json.loads(path.read_text())
 for name,value in record['artifact_sha256'].items():
  if digest(path.parent/name)!=value:raise ValueError(f'artifact changed: {path.parent/name}')
 for name,value in record['config']['source_sha256'].items():
  if digest(ROOT/'src/raceplan'/name)!=value:raise ValueError(f'source changed since experiment: {name}')
seal=json.loads((report/'evaluation_seal.json').read_text())
if seal['freeze_sha256']!=digest(report/'freeze.json'):raise ValueError('frozen choice changed')
freeze=json.loads((report/'freeze.json').read_text())
for path in (raw/'evaluation').glob('*/complete.json'):
 config=json.loads(path.read_text())['config']
 if freeze['selected'] not in config['planners'] or config['seeds']!=freeze['evaluation_seeds']:
  raise ValueError('evaluation does not match frozen choice')
# Record the installed package environment, without shell expansion or secrets.
environment={}
from importlib.metadata import version
for package in ['numpy','Pillow','PyYAML','pytest']:
 environment[package]=version(package)
dump(report/'verification.json',dict(complete_units=len(completed),freeze_verified=True,
    source_and_data_hashes_verified=True,environment=environment,python=sys.version,
    note='Hashes verified in this environment; other-environment numerical reproduction not independently tested.'))
paths=[]
for base in [ROOT/'src/raceplan',ROOT/'tests',ROOT/'docs',ROOT/'maps',ROOT/'scenarios',raw,report,ROOT/'results/figures'/a.name]:
 paths += [p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
paths += list((ROOT/'results').glob('*.py'))
paths += [ROOT/n for n in ['README.md','pyproject.toml','uv.lock']]
paths=sorted(set(paths))
inventory={p.relative_to(ROOT).as_posix():digest(p) for p in paths}
archives=ROOT/'results/packages';archives.mkdir(exist_ok=True)
archive=archives/(a.name+'.zip')
# Derived package is regenerated; original experiment units are never overwritten.
with ZipFile(archive,'w',ZIP_DEFLATED) as z:
 for p in paths:z.write(p,p.relative_to(ROOT).as_posix())
 z.writestr('SHA256SUMS.json',json.dumps(inventory,indent=2))
with ZipFile(archive) as z:
 assert z.testzip() is None
 for name,value in inventory.items():
  assert hashlib.sha256(z.read(name)).hexdigest()==value
print(f'verified {len(completed)} units; ZIP {archive} ({archive.stat().st_size} bytes)',flush=True)
