"""Load explicitly supplied local planner implementations."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

from raceplan.planners.base import Planner


def load_custom_planner(spec: str) -> tuple[Planner, dict]:
    """Load ``path/to/file.py:ClassName``; the class must have no required arguments.

    Loading a Python file executes its code. Only use files you trust.
    """
    filename, separator, classname = spec.rpartition(':')
    if not separator or not filename or not classname.isidentifier():
        raise ValueError('custom planner must be specified as path/to/file.py:ClassName')
    path = Path(filename).resolve()
    if not path.is_file() or path.suffix.lower() != '.py':
        raise ValueError(f'custom planner file not found or not Python: {path}')
    source = path.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    # Include the path so equal files in different directories do not share a module.
    module_name = '_raceplan_custom_' + hashlib.sha256(str(path).encode()).hexdigest() + digest
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise ValueError(f'cannot load custom planner: {path}')
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    try:
        # Execute exactly the bytes recorded above, bypassing stale bytecode caches.
        exec(compile(source, str(path), 'exec'), module.__dict__)
        cls = getattr(module, classname, None)
        if not isinstance(cls, type) or not issubclass(cls, Planner):
            raise ValueError(f'{classname} must subclass raceplan.planners.base.Planner')
        planner = cls()
        if (not isinstance(planner.name, str) or not planner.name.strip()
                or planner.name != planner.name.strip() or ':' in planner.name
                or any(ord(character) < 32 for character in planner.name)):
            raise ValueError('planner name must be non-empty, trimmed, and contain no colon or control characters')
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ValueError(f'cannot load custom planner {spec}: {exc}') from exc
    return planner, {'path': str(path), 'sha256': digest, 'class': classname}
