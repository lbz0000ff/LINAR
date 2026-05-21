"""Check all Python files in the project for syntax errors."""
import ast
import os
import sys

def check_file(filepath):
    """Check a single Python file for syntax errors. Returns list of errors."""
    errors = []
    try:
        with open(filepath, 'rb') as f:
            source_bytes = f.read()
        # Decode as UTF-8 with error replacement for safety
        source = source_bytes.decode('utf-8', errors='replace')
        ast.parse(source, filename=filepath)
    except SyntaxError as e:
        errors.append({
            'file': filepath,
            'line': e.lineno,
            'col': e.offset,
            'msg': e.msg,
            'text': e.text.strip() if e.text else '(unknown)'
        })
    except Exception as e:
        errors.append({
            'file': filepath,
            'line': None,
            'col': None,
            'msg': f'{type(e).__name__}: {e}',
            'text': ''
        })
    return errors

def main():
    root = r'H:\Lily'
    py_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip __pycache__, .git, node_modules, etc.
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__' and d != 'node_modules']
        for fn in filenames:
            if fn.endswith('.py'):
                py_files.append(os.path.join(dirpath, fn))

    total = len(py_files)
    all_errors = []
    ok_count = 0

    for i, fp in enumerate(py_files, 1):
        rel = os.path.relpath(fp, root)
        print(f"[{i:3d}/{total}] {rel} ... ", end='', flush=True)
        errs = check_file(fp)
        if errs:
            all_errors.extend(errs)
            print(f"FAIL ({len(errs)} error(s))")
        else:
            ok_count += 1
            print("OK")

    print(f"\n{'='*70}")
    print(f"Total: {total}  Passed: {ok_count}  Failed: {len(all_errors)}")
    print(f"{'='*70}")

    if all_errors:
        print(f"\n--- Detailed Errors ---\n")
        for e in all_errors:
            print(f"  File: {e['file']}")
            print(f"  Line: {e['line']}, Col: {e['col']}")
            print(f"  Msg:  {e['msg']}")
            print(f"  Text: {e['text']}")
            print()
    
    return len(all_errors)

if __name__ == '__main__':
    sys.exit(main())
