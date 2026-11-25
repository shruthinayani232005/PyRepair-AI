"""Runs INSIDE the child process. Installs an audit hook that blocks dangerous
operations, then executes user_code.py.

NOTE: This is best-effort protection only. Real sandboxing needs stronger
isolation such as Docker containers, gVisor or a locked-down VM.
"""
import os
import sys
import traceback

CWD = os.path.normcase(os.path.realpath(os.getcwd()))
BLOCKED = {"os.system", "os.remove", "os.rmdir", "os.unlink", "os.rename", "os.fork",
           "os.popen", "subprocess.Popen", "socket.connect", "socket.bind",
           "shutil.rmtree", "ctypes.dlopen"}


def hook(event, args):
    if event in BLOCKED or event.startswith(("os.exec", "os.spawn", "os.posix_spawn")):
        raise PermissionError(f"Blocked by PyRepair sandbox: {event}")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = os.fsdecode(args[0])
        mode = args[1] if isinstance(args[1], str) else "r"
        if os.path.basename(path) == ".env":
            raise PermissionError("Blocked by PyRepair sandbox: reading .env files")
        if any(ch in mode for ch in "wax+"):
            if not os.path.normcase(os.path.realpath(path)).startswith(CWD):
                raise PermissionError("Blocked by PyRepair sandbox: writing outside the temp folder")


with open("user_code.py", encoding="utf-8") as f:
    source = f.read()

sys.addaudithook(hook)
try:
    exec(compile(source, "user_code.py", "exec"), {"__name__": "__main__", "__file__": "user_code.py"})
except SystemExit:
    raise
except BaseException as exc:
    # skip this runner's own frame so the traceback only shows user code
    tb = exc.__traceback__.tb_next if exc.__traceback__ else None
    traceback.print_exception(type(exc), exc, tb)
    sys.exit(1)
