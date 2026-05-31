from .tool import Tool
import os
import platform
import re
import difflib
import subprocess

# ---------------------------------------------------------------------------
# Platform-aware forbidden paths
# ---------------------------------------------------------------------------
_is_windows = platform.system() == "Windows"

if _is_windows:
    _sysroot = os.environ.get("SystemRoot", "C:\\Windows")

    FORBIDDEN_PATHS = [
        _sysroot,
        os.path.join(_sysroot, "System32"),
        os.path.join(_sysroot, "System32", "config"),
        os.path.join(_sysroot, "System32", "drivers"),
        os.path.join(_sysroot, "System32", "DriverStore"),
        os.path.join(_sysroot, "System32", "Tasks"),
        os.path.join(_sysroot, "System32", "winevt"),
        os.path.join(_sysroot, "System32", "LogFiles"),
        os.path.join(_sysroot, "System32", "GroupPolicy"),
        os.path.join(_sysroot, "System32", "com\dmp"),
        os.path.join(_sysroot, "System32", "restore"),
        os.path.join(_sysroot, "System32", "catroot"),
        os.path.join(_sysroot, "System32", "catroot2"),
        os.path.join(_sysroot, "System32", "spool"),
        os.path.join(_sysroot, "System32", "MsDtc"),
        os.path.join(_sysroot, "System32", "Tasks\Microsoft\Windows\SystemRestore"),
        os.path.join(_sysroot, "System32", "Tasks\Microsoft\Windows\RAC"),
        os.path.join(_sysroot, "System32", "Tasks\Microsoft\Windows\DiskDiagnostic"),
        os.path.join("C:\\", "Program Files"),
        os.path.join("C:\\", "Program Files (x86)"),
        os.path.join("C:\\", "ProgramData"),
        os.path.join("C:\\", "System Volume Information"),
        os.path.join("C:\\", "$Recycle.Bin"),
        os.path.join("C:\\", "Boot"),
        os.path.join("C:\\", "Recovery"),
        os.path.join("C:\\", "PerfLogs"),
        os.path.join("C:\\", "Windows.old"),
    ]

    BLOCKED_DEVICE_PATHS = [
        "NUL", "CON", "PRN", "AUX",
    ] + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)]

    # Raw device paths (Win32 device namespace)
    BLOCKED_RAW_DEVICE_PREFIXES = [
        "\\\\.\\PhysicalDrive",
        "\\\\.\\Global\\",
        "\\\\.\\",
    ]

    # System files on root that are huge / sensitive
    BLOCKED_ROOT_SYSTEM_FILES = [
        "hiberfil.sys", "pagefile.sys", "swapfile.sys",
        "$LogFile", "$Mft", "$MftMirr", "$Boot",
        "$BadClus", "$Secure", "$UpCase", "$Extend",
        "$Volume", "$Directory", "$AttrDef", "$Bitmap",
    ]

    # DOS reserved names as a compiled regex for fast checking
    DOS_RESERVED_RE = re.compile(
        r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$", re.IGNORECASE
    )
else:
    FORBIDDEN_PATHS = [
        "/", "/root", "/etc", "/var", "/usr", "/bin", "/sbin",
        "/lib", "/lib64", "/dev", "/proc", "/sys",
    ]

    BLOCKED_DEVICE_PATHS = [
        "/dev/zero", "/dev/random", "/dev/urandom", "/dev/null",
        "/dev/fd/0", "/dev/fd/1", "/dev/fd/2",
        "/dev/stdin", "/dev/stdout", "/dev/stderr",
        "/dev/console", "/dev/tty",
    ]

ABSOLUTE_MAX_SIZE = 10 * 1024 * 1024   # 10 MB hard cap
DEFAULT_MAX_SIZE = 50 * 1024           # 50 KB default cap
DEFAULT_LIMIT = 200
MAXIMUM_LIMIT = 5000
WRITE_MAX_CONTENT = 5 * 1024 * 1024    # 5 MB max content per write


def _check_path_safety(file_path):
    """Shared path security check. Returns (abs_path, real_path) on success,
    or an error dict on failure."""
    if not file_path or not isinstance(file_path, str):
        return {"error": "file_path is required and must be a non-empty string."}

    # ── path traversal ──
    normalized = file_path.replace("\\", "/")
    if ".." in normalized.split("/"):
        return {"error": "Path traversal detected: '..' is not allowed in file paths."}

    abs_path = os.path.abspath(file_path)
    real_path = os.path.realpath(abs_path)

    # ── Windows-specific checks ──
    if _is_windows:
        filename = os.path.basename(real_path)
        if DOS_RESERVED_RE.match(filename):
            return {"error": f"Access denied: '{file_path}' is a reserved DOS device name."}
        for prefix in BLOCKED_RAW_DEVICE_PREFIXES:
            if abs_path.startswith(prefix):
                return {"error": f"Access denied: '{file_path}' is a raw device path."}
        parent = os.path.dirname(real_path)
        if parent.rstrip(os.sep).endswith(":") or parent.rstrip(os.sep).endswith(":\\"):
            if filename.lower() in BLOCKED_ROOT_SYSTEM_FILES:
                return {"error": f"Access denied: '{file_path}' is a protected system file."}

    # ── device paths ──
    for device in BLOCKED_DEVICE_PATHS:
        if real_path == device:
            return {"error": f"Access denied: '{file_path}' is a blocked device path."}

    # ── forbidden system directories (case-insensitive on Windows) ──
    sep = os.sep
    cmp_path = real_path.lower() if _is_windows else real_path
    for forbidden in FORBIDDEN_PATHS:
        f_norm = forbidden.replace("/", sep)
        fc = f_norm.lower() if _is_windows else f_norm
        if cmp_path == fc or cmp_path.startswith(fc + sep):
            return {"error": f"Access denied: '{file_path}' is in a protected system directory."}

    return (abs_path, real_path)


class Tool_ReadFile(Tool):
    name: str = "read_file"
    description: str = "Read the contents of a file."
    tool_schema: dict = {
        "name": "read_file",
        "description": "Reads the contents of a text file with security checks. "
                       "Supports pagination via offset/limit. "
                       "Binary files and files over the size limit are rejected.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to read."
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting line number (1-based). Optional."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to return. "
                                   f"Optional, defaults to {DEFAULT_LIMIT}."
                },
                "max_size": {
                    "type": "integer",
                    "description": "Override the file size limit in bytes. "
                                   f"Optional, capped at {ABSOLUTE_MAX_SIZE}."
                }
            },
            "required": ["file_path"]
        }
    }

    def execute(self, *args, **kwargs):
        file_path = kwargs.get("file_path")
        offset = kwargs.get("offset")
        limit = kwargs.get("limit")
        max_size = kwargs.get("max_size")

        # ── security checks ──
        checked = _check_path_safety(file_path)
        if isinstance(checked, dict):
            return checked
        abs_path, real_path = checked

        # ── existence & type checks ──
        if not os.path.exists(abs_path):
            return {"error": f"File not found: {file_path}"}

        if not os.path.isfile(abs_path):
            return {"error": f"'{file_path}' is not a regular file."}

        # ── file size check ──
        try:
            file_size = os.path.getsize(abs_path)
        except OSError as e:
            return {"error": f"Cannot determine file size: {e}"}

        effective_max = min(max_size, ABSOLUTE_MAX_SIZE) if max_size is not None else DEFAULT_MAX_SIZE
        if file_size > effective_max:
            return {
                "error": (
                    f"File size ({file_size} bytes) exceeds the maximum allowed "
                    f"({effective_max} bytes). "
                    f"You can increase the limit with max_size (max {ABSOLUTE_MAX_SIZE} bytes)."
                )
            }

        # ── read raw bytes ──
        try:
            with open(abs_path, "rb") as f:
                raw_data = f.read()
        except PermissionError:
            return {"error": f"Permission denied: Cannot read '{file_path}'."}
        except OSError as e:
            return {"error": f"Error reading '{file_path}': {e}"}

        # ── binary detection (null byte in first 8KB) ──
        if b"\x00" in raw_data[:8192]:
            return {"error": f"Binary file detected: '{file_path}' is not a text file."}

        # ── decode as UTF-8 ──
        try:
            text = raw_data.decode("utf-8")
        except UnicodeDecodeError:
            return {"error": f"File '{file_path}' is not valid UTF-8 text."}

        # ── pagination ──
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)

        offset = offset if offset is not None else 1
        limit = limit if limit is not None else DEFAULT_LIMIT
        limit = min(limit, MAXIMUM_LIMIT)

        start_idx = max(0, offset - 1)
        end_idx = min(start_idx + limit, total_lines)
        selected = lines[start_idx:end_idx]

        return {
            "content": "".join(selected),
            "total_lines": total_lines,
            "returned_lines": len(selected),
            "offset": offset,
            "limit": limit,
        }

class Tool_WriteFile(Tool):
    name: str = "write_file"
    description: str = "Write content to a file."
    tool_schema: dict = {
        "name": "write_file",
        "description": "Writes text content to a file with security checks. "
                       "Mode 'append' adds content as-is (no auto newline). "
                       "Protected locations are rejected.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to write."
                },
                "content": {
                    "type": "string",
                    "description": "The text content to write to the file."
                },
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "default": "overwrite",
                    "description": "Whether to overwrite the file or append to it."
                }
            },
            "required": ["file_path", "content"]
        }
    }

    def execute(self, *args, **kwargs):
        file_path = kwargs.get("file_path")
        content = kwargs.get("content")
        mode = kwargs.get("mode", "overwrite")

        # ── validate parameters ──
        if not file_path or not isinstance(file_path, str):
            return {"error": "file_path is required and must be a non-empty string."}
        if content is None or not isinstance(content, str):
            return {"error": "content is required and must be a string."}
        if mode not in ("overwrite", "append"):
            return {"error": "mode must be 'overwrite' or 'append'."}

        # ── content size limit ──
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > WRITE_MAX_CONTENT:
            return {
                "error": f"Content size ({len(content_bytes)} bytes) exceeds the maximum "
                         f"allowed ({WRITE_MAX_CONTENT} bytes)."
            }

        # ── security checks ──
        checked = _check_path_safety(file_path)
        if isinstance(checked, dict):
            return checked
        abs_path, real_path = checked

        # ── warn if overwriting an existing file ──
        existed = os.path.exists(abs_path)
        if existed and mode == "overwrite":
            if not os.path.isfile(abs_path):
                return {"error": f"'{file_path}' is not a regular file."}

        # ── create parent directories ──
        parent = os.path.dirname(abs_path)
        if parent and not os.path.exists(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as e:
                return {"error": f"Cannot create directory '{parent}': {e}"}

        # ── write ──
        open_mode = "a" if mode == "append" else "w"
        try:
            with open(abs_path, open_mode, encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return {"error": f"Error writing to '{file_path}': {e}"}

        return {
            "bytes_written": len(content_bytes),
            "mode": mode,
            "target": file_path,
        }
        
class Tool_DeleteFile(Tool):
    name: str = "delete_file"
    description: str = "Delete a file."
    tool_schema: dict = {
        "name": "delete_file",
        "description": "Deletes a specified file with security checks. Deleting files in protected locations or non-regular files is rejected.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to delete."
                }
            },
            "required": ["file_path"]
        }
    }

    def execute(self, *args, **kwargs):
        file_path = kwargs.get("file_path")

        # ── security checks ──
        checked = _check_path_safety(file_path)
        if isinstance(checked, dict):
            return checked
        abs_path, real_path = checked

        # ── existence & type checks ──
        if not os.path.exists(abs_path):
            return {"error": f"File not found: {file_path}"}

        if not os.path.isfile(abs_path):
            return {"error": f"'{file_path}' is not a regular file."}

        # ── delete ──
        try:
            os.remove(abs_path)
        except OSError as e:
            return {"error": f"Error deleting '{file_path}': {e}"}

        return {
            "deleted": file_path,
        }

class Tool_DeleteDir(Tool):
    name: str = "delete_dir"
    description: str = "Delete a directory."
    tool_schema: dict = {
        "name": "delete_dir",
        "description": "Recursively deletes a directory with security checks. "
                       "Will not delete the home directory or drive roots.",
        "parameters": {
            "type": "object",
            "properties": {
                "dir_path": {
                    "type": "string",
                    "description": "The absolute path to the directory to delete."
                }
            },
            "required": ["dir_path"]
        }
    }

    def execute(self, *args, **kwargs):
        dir_path = kwargs.get("dir_path")

        if not dir_path or not isinstance(dir_path, str):
            return {"error": "dir_path is required and must be a non-empty string."}

        # ── security checks ──
        checked = _check_path_safety(dir_path)
        if isinstance(checked, dict):
            return checked
        abs_path, real_path = checked

        # ── existence & type checks ──
        if not os.path.exists(abs_path):
            return {"error": f"Directory not found: {dir_path}"}

        if not os.path.isdir(abs_path):
            return {"error": f"'{dir_path}' is not a directory."}

        # ── extra safety: refuse to delete home or drive root ──
        home = os.path.realpath(os.path.expanduser("~"))
        cmp_path = real_path.lower() if _is_windows else real_path
        cmp_home = home.lower() if _is_windows else home

        if cmp_path == cmp_home:
            return {"error": "Refusing to delete the home directory."}

        # Drive root check (e.g. C:\, D:\ on Windows, / on Unix)
        parent = os.path.dirname(real_path)
        if parent == real_path or (
            _is_windows and re.match(r"^[A-Za-z]:\\?$", real_path)
        ):
            return {"error": "Refusing to delete a drive root."}

        # ── delete ──
        import shutil
        try:
            shutil.rmtree(abs_path)
        except OSError as e:
            return {"error": f"Error deleting directory '{dir_path}': {e}"}

        return {
            "deleted": dir_path,
        }

def _fuzzy_find_replace(text, old, new, replace_all=False):
    """Find *old* in *text* and replace with *new*, with fuzzy matching.

    Returns (new_text, count, confidence) where confidence is 0-1.
    Falls back gracefully: tries exact → whitespace-normalized → difflib.
    """
    if not old:
        return (text, 0, 1.0)

    # Level 1: exact match
    if old in text:
        count = text.count(old)
        if replace_all:
            return (text.replace(old, new), count, 1.0)
        return (text.replace(old, new, 1), 1, 1.0)

    # Level 2: normalize trailing whitespace and try again
    def _norm(s):
        return "\n".join(line.rstrip() for line in s.splitlines())

    n_text = _norm(text)
    n_old = _norm(old)
    if n_old in n_text:
        count = n_text.count(n_old)
        if replace_all:
            return (n_text.replace(n_old, new), count, 0.9)
        return (n_text.replace(n_old, new, 1), 1, 0.9)

    # Level 3: difflib fuzzy match
    matcher = difflib.SequenceMatcher(None, text, old)
    ratio = matcher.quick_ratio()
    if ratio >= 0.7:
        for block in matcher.get_matching_blocks():
            if block.size > 0 and block.size >= len(old) * 0.7:
                result = text[:block.a] + new + text[block.a + block.size:]
                return (result, 1, round(ratio, 2))
        blocks = [b for b in matcher.get_matching_blocks() if b.size > 0]
        if blocks:
            best = max(blocks, key=lambda b: b.size)
            result = text[:best.a] + new + text[best.a + best.size:]
            return (result, 1, round(ratio, 2))

    return (text, 0, 0.0)

class Tool_PatchFile(Tool):
    name: str = "patch_file"
    description: str = "Modify a file by finding and replacing text."
    tool_schema: dict = {
        "name": "patch_file",
        "description": "Finds text in a file and replaces it. "
                       "Supports fuzzy matching when exact match fails. "
                       "Returns a diff showing the changes. "
                       "Prefer this over write_file for targeted edits.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to modify."
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find (fuzzy fallback if not found). "
                                   "Include enough context for a unique match."
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement text."
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences instead of just the first.",
                    "default": False
                }
            },
            "required": ["file_path", "old_string", "new_string"]
        }
    }

    def execute(self, *args, **kwargs):
        file_path = kwargs.get("file_path")
        old_string = kwargs.get("old_string")
        new_string = kwargs.get("new_string")
        replace_all = kwargs.get("replace_all", False)

        # ── validate parameters ──
        if not file_path or not isinstance(file_path, str):
            return {"error": "file_path is required and must be a non-empty string."}
        if not old_string or not isinstance(old_string, str):
            return {"error": "old_string is required and must be a non-empty string."}
        if new_string is None or not isinstance(new_string, str):
            return {"error": "new_string is required and must be a string."}

        # ── security checks ──
        checked = _check_path_safety(file_path)
        if isinstance(checked, dict):
            return checked
        abs_path, real_path = checked

        # ── read current content ──
        if not os.path.exists(abs_path):
            return {"error": f"File not found: {file_path}"}
        if not os.path.isfile(abs_path):
            return {"error": f"'{file_path}' is not a regular file."}

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                original = f.read()
        except OSError as e:
            return {"error": f"Error reading '{file_path}': {e}"}

        # ── apply patch ──
        patched, count, confidence = _fuzzy_find_replace(
            original, old_string, new_string, replace_all
        )

        if count == 0:
            return {
                "error": (
                    f"Could not find matching text in '{file_path}'."
                    f"\n\nTip: Make sure to include surrounding context lines "
                    f"for a unique match. The text you provided matched at "
                    f"{confidence*100:.0f}% confidence — need at least 70%."
                )
            }

        # ── generate diff ──
        orig_lines = original.splitlines(keepends=True)
        new_lines = patched.splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(
            orig_lines, new_lines,
            fromfile=file_path, tofile=file_path,
            n=3
        ))
        diff = "".join(diff_lines)

        # ── write back ──
        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(patched)
        except OSError as e:
            return {"error": f"Error writing to '{file_path}': {e}"}

        # ── verify by re-reading ──
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                verified = f.read()
        except OSError:
            verified = None

        if verified is not None and verified != patched:
            return {
                "warning": "Written content differs from expected (possible encoding issue).",
                "diff": diff,
                "matches": count,
                "confidence": confidence,
                "target": file_path,
            }

        return {
            "diff": diff,
            "matches": count,
            "confidence": confidence,
            "target": file_path,
        }

class Tool_SearchFiles(Tool):
    name: str = "search_files"
    description: str = "Search for files or content in files."
    tool_schema: dict = {
        "name": "search_files",
        "description": "Searches file contents or filenames. "
                       "Uses ripgrep if available, falls back to built-in tools.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (regex supported)."
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in. Defaults to current directory.",
                },
                "file_glob": {
                    "type": "string",
                    "description": "Optional file pattern filter, e.g. '*.py', '*.md'."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results. Default 30, capped at 200."
                },
                "search_files": {
                    "type": "boolean",
                    "description": "If true, search filenames instead of file content.",
                    "default": False
                }
            },
            "required": ["pattern"]
        }
    }

    _BLOCKED = ("/proc", "/sys", "/dev", "/boot")

    def execute(self, *args, **kwargs):
        pattern = kwargs.get("pattern")
        path = kwargs.get("path")
        file_glob = kwargs.get("file_glob")
        max_results = kwargs.get("max_results", 30)
        search_files = kwargs.get("search_files", False)

        if not pattern or not isinstance(pattern, str):
            return {"error": "pattern is required and must be a non-empty string."}

        max_results = min(max_results, 200)
        search_dir = path if path else os.getcwd()
        if not isinstance(search_dir, str):
            return {"error": "path must be a string."}

        abs_dir = os.path.realpath(os.path.abspath(search_dir))
        if not os.path.isdir(abs_dir):
            return {"error": f"Directory not found: {search_dir}"}

        # Search-specific security: block virtual filesystems
        cmp = abs_dir.lower() if _is_windows else abs_dir
        for b in self._BLOCKED:
            bc = b.lower() if _is_windows else b
            sep = os.sep
            if cmp == bc or cmp.startswith(bc + sep):
                return {"error": f"Search denied: '{search_dir}' is in a restricted area."}

        if search_files:
            return self._search_filenames(pattern, abs_dir, file_glob, max_results)
        return self._search_content(pattern, abs_dir, file_glob, max_results)

    def _search_filenames(self, pattern, abs_dir, file_glob, max_results):
        import fnmatch
        results = []
        try:
            pat = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return {"error": f"Invalid regex pattern: {pattern}"}

        for root, dirs, files in os.walk(abs_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if file_glob and not fnmatch.fnmatch(f, file_glob):
                    continue
                if pat.search(f):
                    results.append({"path": os.path.join(root, f), "filename": f})
                    if len(results) >= max_results:
                        return {"matches": results, "total": len(results), "truncated": True}
        return {"matches": results, "total": len(results), "truncated": False}

    def _search_content(self, pattern, abs_dir, file_glob, max_results):
        for p in ["rg", "rg.exe"]:
            try:
                subprocess.run([p, "--version"], capture_output=True, timeout=5)
                return self._search_with_rg(p, pattern, abs_dir, file_glob, max_results)
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                continue
        return self._search_python(pattern, abs_dir, file_glob, max_results)

    def _decode_output(self, result):
        """Decode subprocess stdout with encoding fallback."""
        if result.stdout is None:
            return ""
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                return result.stdout.decode(enc, errors="replace")
            except (UnicodeDecodeError, UnicodeError):
                continue
        return result.stdout.decode("utf-8", errors="replace")

    def _filter_matches(self, matches):
        """Remove matches from .git and other noisy directories."""
        return [m for m in matches if "/.git/" not in m["path"].replace("\\", "/")
                and "\\.git\\" not in m["path"]]

    def _search_with_rg(self, rg, pattern, abs_dir, file_glob, max_results):
        cmd = [rg, "--line-number", "--no-heading", "--color", "never",
               "-m", str(max_results)]
        if file_glob:
            cmd.extend(["--glob", file_glob])
        cmd.extend([pattern, abs_dir])

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            return {"error": "Search timed out (30s). Try a narrower pattern or path."}
        except OSError as e:
            return {"error": f"Search failed: {e}"}

        matches = []
        for line in self._decode_output(result).splitlines():
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append({"path": parts[0], "line": int(parts[1]), "content": parts[2]})
            elif len(parts) == 2:
                matches.append({"path": parts[0], "line": int(parts[1]), "content": ""})
        matches = self._filter_matches(matches)
        return {"matches": matches, "total": len(matches), "truncated": len(matches) >= max_results}

    def _search_python(self, pattern, abs_dir, file_glob, max_results):
        """Pure Python content search fallback (used when rg is not available)."""
        import fnmatch
        try:
            pat = re.compile(pattern)
        except re.error:
            return {"error": f"Invalid regex pattern: {pattern}"}

        matches = []
        for root, dirs, files in os.walk(abs_dir):
            # Skip .git, node_modules, __pycache__, hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if file_glob and not fnmatch.fnmatch(f, file_glob):
                    continue
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        for i, line in enumerate(fh, 1):
                            if pat.search(line.rstrip("\n\r")):
                                matches.append({
                                    "path": fpath,
                                    "line": i,
                                    "content": line.rstrip("\n\r")[:200],
                                })
                                if len(matches) >= max_results:
                                    return {"matches": matches, "total": len(matches), "truncated": len(matches) >= max_results}
                except (OSError, UnicodeDecodeError):
                    continue
        return {"matches": matches, "total": len(matches), "truncated": False}
