"""Runs Python code in a separate process with a timeout and resource limits.

SAFETY NOTE: user code is NEVER executed in the Streamlit process. We use a
temp directory, a minimal environment (no secrets), CPU/memory/file limits
(Linux/macOS) and an audit hook (core/sandbox_runner.py). This is NOT a full
sandbox - for untrusted code in production use Docker or a VM.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RUNNER = Path(__file__).with_name("sandbox_runner.py")
MAX_OUTPUT = 20000


def _apply_limits(timeout):
    def apply():
        import resource
        for name, value in (("RLIMIT_CPU", timeout + 2), ("RLIMIT_AS", 512 * 2**20),
                            ("RLIMIT_FSIZE", 10 * 2**20), ("RLIMIT_NOFILE", 64)):
            try:
                resource.setrlimit(getattr(resource, name), (value, value))
            except (ValueError, OSError):
                pass  # some limits are unsupported on some systems
    return apply


def parse_error(stderr):
    """Extract exception type, message and line number from a traceback."""
    lines = [l for l in stderr.strip().splitlines() if l.strip()]
    if not lines:
        return "UnknownError", "", None
    last = lines[-1]
    etype, _, msg = last.partition(": ")
    if not re.match(r"^[A-Za-z_][\w.]*$", etype):
        etype, msg = "UnknownError", last
    found = re.findall(r'File "user_code\.py", line (\d+)', stderr)
    return etype.split(".")[-1], msg, int(found[-1]) if found else None


def _text(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return (value or "")[:MAX_OUTPUT]


def run_code(code, timeout=10):
    """Execute code safely; always returns a dict (never raises)."""
    start = time.time()
    result = {"success": False, "stdout": "", "stderr": "", "returncode": None,
              "timed_out": False, "duration": 0.0, "error_type": "", "error_message": "",
              "line_number": None, "traceback": ""}
    tmp = tempfile.mkdtemp(prefix="pyrepair_")
    try:
        Path(tmp, "user_code.py").write_text(code, encoding="utf-8")
        shutil.copy(RUNNER, Path(tmp, "runner.py"))
        env = {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
               "PATH": "/usr/bin:/bin"}
        if os.name == "nt":  # Windows needs this to start Python
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        proc = subprocess.Popen(
            [sys.executable, "-I", "runner.py"], cwd=tmp, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            preexec_fn=_apply_limits(timeout) if os.name == "posix" else None)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()  # terminate runaway process
            out, err = proc.communicate()
            result["timed_out"] = True
            err = _text(err) + f"\nTimeoutError: execution exceeded {timeout} seconds"
        result.update(stdout=_text(out), stderr=_text(err), returncode=proc.returncode)
        result["success"] = proc.returncode == 0 and not result["timed_out"]
        if not result["success"]:
            result["traceback"] = result["stderr"]
            result["error_type"], result["error_message"], result["line_number"] = \
                parse_error(result["stderr"])
    except Exception as exc:  # executor failure must not crash the app
        result.update(stderr=f"ExecutionFailure: {exc}", traceback=str(exc),
                      error_type="ExecutionFailure", error_message=str(exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        result["duration"] = round(time.time() - start, 3)
    return result
