"""The files under tools/ a builder runs: its own modules, followed through their imports, and
the C sources they compile. play.sh rebuilds a level when one of them is newer than it.

    python3 -I tools/deps.py tools/build_map.py [more.py ...]

Reads the sources (ast), runs nothing.
"""
import ast
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))


def module_file(name):
    """tools/a/b.py or tools/a/b/__init__.py for the module a.b, or None when it isn't ours."""
    base = os.path.join(TOOLS, *name.split('.'))
    for path in (base + '.py', os.path.join(base, '__init__.py')):
        if os.path.isfile(path):
            return path
    return None


def imports(path):
    """The module names a source imports (relative ones made absolute)."""
    tree = ast.parse(open(path, encoding='utf-8').read(), path)
    rel = os.path.relpath(path, TOOLS)[:-len('.py')].split(os.sep)
    package = rel[:-1] if rel[-1] != '__init__' else rel[:-1]
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[:len(package) - (node.level - 1)]
                mod = '.'.join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ''
            out.append(mod)
            out += [f'{mod}.{a.name}' if mod else a.name for a in node.names]  # from pkg import module
    return out


def deps(scripts):
    seen, todo = set(), [os.path.abspath(s) for s in scripts]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        src = open(path, encoding='utf-8').read()
        for c in re.findall(r"['\"]([\w-]+\.c)['\"]", src):
            cpath = os.path.join(os.path.dirname(path), c)
            if os.path.isfile(cpath):
                seen.add(cpath)
        for name in imports(path):
            parts = name.split('.')
            for k in range(1, len(parts) + 1):  # a.b.c: a/__init__.py, a/b/__init__.py, a/b/c.py
                f = module_file('.'.join(parts[:k]))
                if f is not None and f not in seen:
                    todo.append(f)
    return sorted(seen)


if __name__ == '__main__':
    for f in deps(sys.argv[1:]):
        print(os.path.relpath(f))
