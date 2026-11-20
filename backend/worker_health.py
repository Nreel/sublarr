"""Container healthcheck for an RQ worker, which has no HTTP listener."""

import os
import socket
from datetime import UTC, datetime


def _pid_exists(pid: int) -> bool:
    """True when ``pid`` names a live process we are allowed to see.

    ``os.kill(pid, 0)`` is the POSIX liveness idiom and is what this used to
    call, but on Windows ``signal.CTRL_C_EVENT`` is 0, so CPython routes
    ``os.kill(pid, 0)`` to ``GenerateConsoleCtrlEvent`` — it does not probe the
    PID, it fires Ctrl-C at that console process group (the caller's own group
    included). Under pytest that raised ``KeyboardInterrupt`` in the controller
    and silently aborted the run halfway; on a native Windows install it would
    interrupt the server's own console. Probe with ``OpenProcess`` instead.
    """
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_ACCESS_DENIED = 5
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # Access denied still proves the PID is taken (same reasoning as the
        # PermissionError branch below).
        return kernel32.GetLastError() == ERROR_ACCESS_DENIED
    try:
        os.kill(pid, 0)
    except PermissionError:
        # Docker healthchecks can run as root without CAP_KILL while gosu
        # runs the worker as PUID. EPERM still proves that the PID exists.
        return True
    except (OSError, TypeError):
        return False
    return True


def worker_is_healthy(worker, *, hostname, now):
    if worker.hostname != hostname or not worker.pid or not worker.last_heartbeat:
        return False
    if not _pid_exists(worker.pid):
        return False
    heartbeat = worker.last_heartbeat
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    # Idle RQ workers block for almost worker_ttl; busy workers heartbeat too.
    age = (now - heartbeat).total_seconds()
    return 0 <= age <= worker.worker_ttl + 60


def main():
    from redis import Redis
    from rq import Worker

    try:
        connection = Redis.from_url(
            os.environ["SUBLARR_REDIS_URL"], socket_connect_timeout=3, socket_timeout=3
        )
        workers = Worker.all(connection=connection)
        healthy = any(
            worker_is_healthy(w, hostname=socket.gethostname(), now=datetime.now(UTC))
            for w in workers
        )
    except Exception:
        # Do not log the connection URL: it can contain a Redis password.
        healthy = False
    print("RQ worker healthy" if healthy else "RQ worker unavailable or heartbeat stale")
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
