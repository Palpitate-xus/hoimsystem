import os
from pathlib import Path

from prometheus_client import multiprocess


def on_starting(server):
    """Discard metrics left by a previous Gunicorn master in this container."""
    metrics_dir = os.getenv("PROMETHEUS_MULTIPROC_DIR")
    if not metrics_dir:
        return
    directory = Path(metrics_dir)
    directory.mkdir(parents=True, exist_ok=True)
    for metric_file in directory.glob("*.db"):
        metric_file.unlink()


def child_exit(server, worker):
    multiprocess.mark_process_dead(worker.pid)
