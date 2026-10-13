"""One-command ordered pipeline; completed units resume only after config/hash checks."""
import argparse
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--name',default='research_20261013')
a=p.parse_args()
if Path(a.name).name!=a.name or a.name in {'.','..'}:p.error('invalid run name')
def call(script,*args):
 subprocess.run([sys.executable,str(ROOT/'results'/script),*args,'--name',a.name],cwd=ROOT,check=True)
call('research_pipeline.py','sensitivity')
call('research_pipeline.py','validation')
if not (ROOT/'results/analysis'/a.name/'freeze.json').exists():call('research_pipeline.py','tune')
call('research_pipeline.py','evaluation')
call('research_measurement.py')
call('research_report.py')
call('research_failure_report.py')
call('research_package.py')
