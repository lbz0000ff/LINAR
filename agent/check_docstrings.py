#!/usr/bin/env python3
"""AST-based checker: find classes and functions without docstrings."""
import ast
import os
import sys

# Directories to skip (virtual envs, third-party, etc.)
SKIP_DIRS = {
    '__pycache__', '.git', '.venv', 'venv', 'env', 'node_modules',
    '.tox', '.eggs', 'build', 'dist',
}

def has_docstring(node: ast.AST) -> bool:
    """Check if an AST node's body starts with a docstring (string literal expression)."""
    body = getattr(node, 'body', [])
    if not body:
        return False  # empty body technically has no docstring
    first = body[0]
    # Docstring = first statement is an Expr whose value is a constant string
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        return isinstance(first.value.value, str)
    return False


def check_file(filepath: str) -> list[dict]:
    """Parse a Python file and return all classes/functions without docstrings."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError, OSError) as e:
        return [{'file': filepath, 'name': '<parse error>', 'type': 'error', 'line': 0, 'reason': str(e)}]

    results = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if not has_docstring(node):
                results.append({
                    'file': filepath,
                    'name': node.name,
                    'type': 'class',
                    'line': node.lineno,
                })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not has_docstring(node):
                results.append({
                    'file': filepath,
                    'name': node.name,
                    'type': 'function',
                    'line': node.lineno,
                })

    return results


def walk_py_files(root: str) -> list[str]:
    """Yield all .py file paths under root, skipping unwanted dirs."""
    py_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith('.py'):
                py_files.append(os.path.join(dirpath, fn))
    return py_files


def main():
    if len(sys.argv) < 2:
        roots = ['H:\\Lily']
    else:
        roots = sys.argv[1:]

    all_results = []
    parse_errors = []

    for root in roots:
        if not os.path.isdir(root):
            print(f"[WARN] Not a directory: {root}", file=sys.stderr)
            continue
        for filepath in walk_py_files(root):
            res = check_file(filepath)
            for item in res:
                if item['type'] == 'error':
                    parse_errors.append(item)
                else:
                    all_results.append(item)

    # Sort by file then line
    all_results.sort(key=lambda x: (x['file'], x['line']))

    # --- Report ---
    print("=" * 80)
    print("CLASSES AND FUNCTIONS WITHOUT DOCSTRINGS")
    print("=" * 80)

    if not all_results:
        print("(none — everything has a docstring!)")

    current_file = None
    for item in all_results:
        if item['file'] != current_file:
            current_file = item['file']
            # Show relative path
            try:
                rel = os.path.relpath(current_file, 'H:\\Lily')
            except ValueError:
                rel = current_file
            print(f"\n── {rel} ──")
        print(f"  [{item['type']:8}] {item['name']}  (line {item['line']})")

    # Summary counts
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    n_classes = sum(1 for r in all_results if r['type'] == 'class')
    n_funcs = sum(1 for r in all_results if r['type'] == 'function')
    print(f"  Classes without docstring:   {n_classes}")
    print(f"  Functions without docstring:  {n_funcs}")
    print(f"  Total:                        {n_classes + n_funcs}")

    if parse_errors:
        print(f"\n  Parse errors: {len(parse_errors)}")
        for e in parse_errors:
            print(f"    {e['file']}: {e['reason']}")

    print()


if __name__ == '__main__':
    main()
