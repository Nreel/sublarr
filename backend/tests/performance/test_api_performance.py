"""Performance tests for API endpoints using pytest-benchmark."""

import os

import pytest

# pytest-benchmark switches itself off in xdist workers, and these tests read
# benchmark.stats["mean"] — under `-n auto` that is None and every one of them
# dies with a TypeError. The suite defaults to xdist now, so skip instead of
# failing: run `pytest -p no:xdist tests/performance` for the real numbers.
pytestmark = pytest.mark.skipif(
    "PYTEST_XDIST_WORKER" in os.environ,
    reason="pytest-benchmark is disabled in xdist workers; run serially",
)


@pytest.mark.benchmark
class TestAPIPerformance:
    """Performance tests for API endpoints."""

    def test_health_endpoint_performance(self, client, benchmark, monkeypatch):
        """Benchmark health endpoint response time."""
        from extensions import limiter

        # /health is limited to 60/minute; the benchmark's 100+ rounds measure
        # the endpoint, not the limiter's 429.
        monkeypatch.setattr(limiter, "enabled", False)
        result = benchmark(client.get, "/api/v1/health")
        assert result.status_code == 200
        # Health checks providers (may involve network); generous threshold
        assert benchmark.stats["mean"] < 5.0  # 5s

    def test_stats_endpoint_performance(self, client, benchmark):
        """Benchmark stats endpoint response time."""
        result = benchmark(client.get, "/api/v1/stats")
        assert result.status_code == 200
        # Stats should be reasonably fast (< 500ms)
        assert benchmark.stats["mean"] < 0.5

    def test_wanted_endpoint_performance(self, client, benchmark):
        """Benchmark wanted endpoint response time."""
        result = benchmark(client.get, "/api/v1/wanted?page=1&per_page=50")
        assert result.status_code == 200
        # Wanted list should be reasonably fast (< 500ms)
        assert benchmark.stats["mean"] < 0.5

    def test_providers_endpoint_performance(self, client, benchmark):
        """Benchmark providers endpoint response time."""
        result = benchmark(client.get, "/api/v1/providers")
        assert result.status_code == 200
        # Provider status should be fast (< 500ms)
        assert benchmark.stats["mean"] < 0.5


@pytest.mark.benchmark
class TestDatabasePerformance:
    """Performance tests for database operations."""

    def test_get_wanted_items_performance(self, app_ctx, benchmark):
        """Benchmark wanted items query performance."""
        from db.wanted import get_wanted_items

        result = benchmark(get_wanted_items, page=1, per_page=50)
        assert "data" in result
        # Database query should be fast (< 500ms)
        assert benchmark.stats["mean"] < 0.5

    def test_get_history_performance(self, app_ctx, benchmark):
        """Benchmark history query performance."""
        from db.library import get_download_history

        result = benchmark(get_download_history, page=1, per_page=50)
        assert "data" in result
        # Database query should be fast (< 500ms)
        assert benchmark.stats["mean"] < 0.5
