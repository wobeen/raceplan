"""Find the planner classes of a user planner file without running it.

The run dialog offers the classes it finds as checkboxes; a checked class becomes the usual ``FILE.py:CLASS``. The file
is parsed (``ast``), never imported or executed: reading it is not yet a decision to trust it. Only top-level classes
count, and a class counts when one of its bases is RacePlan's ``Planner`` (or one of the built-in planner classes),
reached through ``from raceplan.planners import ...``, ``from raceplan.planners.base import Planner``, ``import
raceplan.planners as name``, their aliases, or another class of the same file that counts. Anything decided at run
time (star imports, conditional definitions, bases from the user's other modules) is not guessed: such classes are
listed as "other" and can still be typed by hand. The loader in the comparison process stays the judge.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import stat

from raceplan import planners as builtin_planners

MAX_BYTES = 1024 * 1024
MODULES = ('raceplan.planners', 'raceplan.planners.base')
BASES = frozenset(name for name in builtin_planners.__all__
                  if isinstance(getattr(builtin_planners, name), type) and issubclass(getattr(builtin_planners, name),
                                                                                       builtin_planners.Planner))


class ScanError(ValueError):
    pass


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return '.'.join([node.id, *reversed(parts)])
    return None


def _known_names(tree):
    """Names bound at module level to a planner base class, and module aliases that lead to raceplan.planners."""
    names, modules = {}, set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in MODULES:
            for alias in node.names:
                if alias.name in BASES and (node.module == 'raceplan.planners' or alias.name == 'Planner'):
                    names[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == 'raceplan':
            for alias in node.names:
                if alias.name == 'planners':
                    modules.add(alias.asname or 'planners')
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in MODULES:
                    modules.add(alias.asname or alias.name)
    return names, modules


def _rebound(node):
    """Module-level names a statement (other than an import or a class) binds anew."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return {node.name}
    if isinstance(node, ast.AnnAssign) and node.value is None:
        return set()  # `Planner: type` only annotates; the name keeps what it was.
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {item.id for target in targets for item in ast.walk(target) if isinstance(item, ast.Name)}
    return set()


def classes(text_path):
    """Planner classes of one local .py file: {'file', 'planners': [{'name', 'line', 'base'}], 'other': [...]}.
    The module is followed top to bottom the way Python binds it: a base counts only if it is a planner class at the
    point the class is defined, a name bound again later loses what it was, and a class defined twice is the last one
    (what the loader gets)."""
    if not isinstance(text_path, str) or not text_path.strip():
        raise ScanError('give the path of a .py file')
    text_path = text_path.strip().strip('"')
    if text_path.startswith(('\\\\', '//')):
        raise ScanError('planner files must be on this computer, not a network share')
    path = Path(text_path).expanduser().resolve()
    if str(path).startswith(('\\\\', '//')):
        raise ScanError('planner files must be on this computer, not a network share')
    if path.suffix.lower() != '.py' or not path.is_file():
        raise ScanError(f'not a Python file on this computer: {path}')
    try:
        with path.open('rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):  # What was opened, not just what was checked.
                raise ScanError(f'not a regular file: {path}')
            source = stream.read(MAX_BYTES + 1)  # Bounded even if the file grows after it was checked.
    except OSError as exc:
        raise ScanError(f'cannot read {path.name}: {exc.strerror or exc}') from None
    if len(source) > MAX_BYTES:
        raise ScanError(f'{path.name} is larger than {MAX_BYTES // 1024} KiB; type FILE.py:CLASS by hand')
    try:
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, ValueError) as exc:  # ValueError: e.g. a null byte in the file
        where = f' line {exc.lineno}' if isinstance(exc, SyntaxError) else ''
        raise ScanError(f'{path.name}{where}: cannot be parsed ({getattr(exc, "msg", exc)}); fix it or type FILE.py:CLASS '
                        'by hand') from None
    bound, modules, found, defined = {}, set(), {}, {}  # bound: name -> planner base it stands for at this point
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names, module_names = _known_names(ast.Module(body=[node], type_ignores=[]))
            for alias in node.names:
                local = alias.asname or alias.name.partition('.')[0]
                bound.pop(local, None)
                modules.discard(local)
            bound.update(names)
            modules |= module_names
        elif isinstance(node, ast.ClassDef):
            via = None
            for base in node.bases:
                dotted = _dotted(base) or ''
                head, _, last = dotted.rpartition('.')
                via = bound.get(dotted) or (last if head in modules and last in BASES else None)
                if via is not None:
                    break
            defined[node.name] = node.lineno
            found.pop(node.name, None)
            bound.pop(node.name, None)
            if via is not None:
                found[node.name] = {'name': node.name, 'line': node.lineno, 'base': via}
                bound[node.name] = node.name
        else:
            for name in _rebound(node):
                bound.pop(name, None)
                found.pop(name, None)
                modules.discard(name)
    planners = sorted(found.values(), key=lambda item: item['line'])
    other = [{'name': name, 'line': line} for name, line in sorted(defined.items(), key=lambda item: item[1])
             if name not in found]
    return {'file': str(path), 'planners': planners, 'other': other}
