"""The script sandbox (bible section 7).

Each script runs in a separate background program (a "worker process"), so
a broken script can never crash the app or touch anything else:

  - a time limit: no answer within the limit and the worker is stopped (2 seconds
    for indicators; long backtests must keep reporting progress)
  - a memory limit (on Windows this needs a later upgrade; see NEEDS_NATHAN.md)
  - only approved functions: no files, no network, no other scripts, and
    imports limited to math, statistics, numpy and pandas
  - scripts never place orders: they return signals, which go through the risk guard

This is safe enough while the owner is the only author. Before running other
people's scripts it needs stronger isolation (bible section 7).
"""

import builtins
import multiprocessing
import sys
import threading
import time
import uuid

INDICATOR_TIME_LIMIT = 2.0
MEMORY_LIMIT_BYTES = 2 * 1024 ** 3

ALLOWED_MODULES = {"math", "statistics", "numpy", "pandas", "datetime", "collections", "itertools", "functools", "random", "dataclasses", "typing"}

SAFE_BUILTINS = [
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "format", "frozenset",
    "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next", "pow", "range",
    "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip", "hasattr", "getattr",
    "Exception", "ValueError", "TypeError", "IndexError", "KeyError", "ZeroDivisionError", "ArithmeticError",
    "StopIteration", "RuntimeError", "AttributeError", "True", "False", "None", "object", "property",
    "staticmethod", "classmethod", "super", "callable", "chr", "ord", "hash", "id", "type",
]


class ScriptError(Exception):
    def __init__(self, info: dict):
        super().__init__(info.get("message", "Script error"))
        self.info = info


# ===========================================================================
# Inside the worker process
# ===========================================================================


def _limited_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] not in ALLOWED_MODULES:
        raise ImportError(f"Scripts can't import '{name}'")
    return builtins.__import__(name, globals, locals, fromlist, level)


def _lock_down() -> None:
    """Remove the worker's ability to use the network, and cap its memory where the system allows."""
    import socket

    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise PermissionError("Scripts can't use the network.")

    socket.socket = NoNetwork
    socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(PermissionError("Scripts can't use the network."))
    if sys.platform != "win32":
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
        except (ImportError, ValueError, OSError):
            pass


def make_namespace(outputs_module) -> dict:
    """The names a script can see: safe built-ins plus the helper library."""
    safe = {name: getattr(builtins, name) for name in SAFE_BUILTINS if hasattr(builtins, name)}
    safe["__import__"] = _limited_import
    safe["__build_class__"] = builtins.__build_class__
    safe["print"] = lambda *args, **kwargs: outputs_module._outputs.messages.append(" ".join(str(a) for a in args))
    namespace = {"__builtins__": safe, "__name__": "script"}
    namespace.update(outputs_module.SCRIPT_NAMES)
    return namespace


def compile_script(code: str):
    from engine.scripting import library
    from engine.scripting.errors import SCRIPT_FILENAME

    namespace = make_namespace(library)
    exec(compile(code, SCRIPT_FILENAME, "exec"), namespace)
    return namespace


def worker_main(connection) -> None:
    """The worker's main loop: receive a job, run it, send back the result."""
    _lock_down()
    from engine.scripting import worker_jobs

    sessions: dict[str, dict] = {}
    while True:
        try:
            job = connection.recv()
        except (EOFError, OSError):
            return
        if job is None:
            return
        try:
            result = worker_jobs.run(job, sessions, lambda progress: connection.send({"heartbeat": progress}))
            connection.send({"ok": True, "result": result})
        except BaseException as error:  # anything the script does wrong
            from engine.scripting import library
            from engine.scripting.errors import explain
            known = list(library.SCRIPT_NAMES) + ["data", "position", "inputs"]
            connection.send({"ok": False, "error": explain(error, known)})


# ===========================================================================
# In the engine: managing workers
# ===========================================================================


class ScriptWorker:
    """One worker process. Restarted automatically after a timeout or crash."""

    def __init__(self, name: str = "scripts"):
        self.name = name
        self._context = multiprocessing.get_context("spawn")   # same behaviour on Windows and elsewhere
        self._lock = threading.Lock()
        self._process = None
        self._connection = None
        self.restarts = 0

    def _start(self) -> None:
        parent, child = self._context.Pipe()
        self._process = self._context.Process(target=worker_main, args=(child,), name=f"script-{self.name}", daemon=True)
        self._process.start()
        child.close()
        self._connection = parent

    def _stop(self) -> None:
        if self._process is not None:
            self._process.kill()
            self._process.join(timeout=2)
        self._process = None
        self._connection = None

    def call(self, job: dict, time_limit: float = INDICATOR_TIME_LIMIT, on_progress=None) -> dict:
        """Run a job. Raises ScriptError with a plain English message if the script fails or runs too long.

        The time limit applies between messages: a long backtest that keeps
        reporting progress may run as long as it needs.
        """
        with self._lock:
            if self._process is None or not self._process.is_alive():
                self._start()
            try:
                self._connection.send(job)
                while True:
                    if not self._connection.poll(time_limit):
                        self._stop()
                        self.restarts += 1
                        from engine.scripting.errors import timeout_error
                        raise ScriptError(timeout_error(time_limit))
                    reply = self._connection.recv()
                    if "heartbeat" in reply:
                        if on_progress:
                            on_progress(reply["heartbeat"])
                        continue
                    if reply["ok"]:
                        return reply["result"]
                    raise ScriptError(reply["error"])
            except (EOFError, OSError, BrokenPipeError):
                self._stop()
                self.restarts += 1
                raise ScriptError({"line": None, "message": "The script stopped unexpectedly (it may have used too much memory) and was restarted.", "details": ""})

    def warm_up(self) -> None:
        """Start the worker ahead of time so the first indicator appears quickly."""
        try:
            self.call({"kind": "ping"}, time_limit=30)
        except ScriptError:
            pass

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.send(None)
                except (OSError, BrokenPipeError):
                    pass
            self._stop()


def new_session_id() -> str:
    return uuid.uuid4().hex


def now() -> float:
    return time.time()
