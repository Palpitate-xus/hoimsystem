import importlib.util
from pathlib import Path

CONFIG_PATH = Path(__file__).parents[1] / "gunicorn.conf.py"
SPEC = importlib.util.spec_from_file_location("hoimsystem_gunicorn_conf", CONFIG_PATH)
gunicorn_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gunicorn_config)


def test_gunicorn_start_removes_only_stale_metric_databases(tmp_path, monkeypatch):
    stale_counter = tmp_path / "counter_123.db"
    stale_gauge = tmp_path / "gauge_all_123.db"
    unrelated = tmp_path / "keep.txt"
    for path in (stale_counter, stale_gauge, unrelated):
        path.write_text("test")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))

    gunicorn_config.on_starting(None)

    assert not stale_counter.exists()
    assert not stale_gauge.exists()
    assert unrelated.read_text() == "test"


def test_gunicorn_start_creates_configured_metrics_directory(tmp_path, monkeypatch):
    metrics_dir = tmp_path / "prometheus"
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(metrics_dir))

    gunicorn_config.on_starting(None)

    assert Path(metrics_dir).is_dir()
