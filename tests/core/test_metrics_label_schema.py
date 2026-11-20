"""A metric's label schema belongs to the metric, not to whichever caller arrived first.

Measured while running `scripts/gen_api_fixtures.py` inside a pytest session that had already imported the
gateway: the script called `metrics.observe("llm_request", 0.42)` without the provider and model that
`raven/core/instrumented.py:28` always passes, so the histogram was constructed with no label names and the
gateway's own next request died inside its metrics call — `ValueError: No label names were set when
constructing histogram:raven_llm_request_duration_seconds`. Reverse the order and the same seam raises
`ValueError: counter metric is missing label values` instead. A metric call sits on the request path, so
neither shape is acceptable: the numbers may be labelled imperfectly, but the call must not decide whether
the request completes.

The same seam, second defect: the collector's text surface spelled labels *inside* the metric name —
`raven_messages_received{channel=webchat}_total 1` — which the exposition grammar does not accept, so a
Prometheus scrape of `/api/metrics/prometheus` dropped every labelled metric while `/api/metrics` reported
them. `prometheus_client`'s own parser is the judge here, because it is the thing a scraper runs.
"""

from __future__ import annotations

from loguru import logger
from prometheus_client import REGISTRY, generate_latest
from prometheus_client.parser import text_string_to_metric_families
from pytest import MonkeyPatch

from raven.core.metrics import MetricsCollector, metrics

SampleKey = tuple[str, tuple[tuple[str, str], ...]]


def _scrape(text: str) -> dict[SampleKey, float]:
    """Every sample a Prometheus parser reads out of one exposition text, keyed by name and labels."""
    scraped: dict[SampleKey, float] = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            scraped[sample.name, tuple(sorted(sample.labels.items()))] = sample.value
    return scraped


def _mirror(metric: str) -> dict[SampleKey, float]:
    """The same reading of the process-wide registry that `MetricsServer.start_http_server` serves."""
    return {key: value for key, value in _scrape(generate_latest().decode("utf-8")).items() if metric in key[0]}


def test_a_counter_whose_calls_disagree_about_labels_counts_every_call() -> None:
    """Whichever shape arrives first owns the schema; the other is projected onto it instead of raising."""
    labelled_first = "gate_counter_labelled_first"
    metrics.inc(labelled_first, {"channel": "webchat"})
    metrics.inc(labelled_first)
    assert REGISTRY.get_sample_value(f"raven_{labelled_first}_total", {"channel": "webchat"}) == 1
    assert REGISTRY.get_sample_value(f"raven_{labelled_first}_total", {"channel": ""}) == 1, (
        "the label-less call was dropped instead of counted under the schema the metric already has"
    )
    snapshot = metrics.snapshot()
    assert snapshot[f"raven_{labelled_first}_total"] == 1
    assert snapshot[f"raven_{labelled_first}{{channel=webchat}}_total"] == 1

    unlabelled_first = "gate_counter_unlabelled_first"
    metrics.inc(unlabelled_first)
    metrics.inc(unlabelled_first, {"channel": "webchat"})
    assert REGISTRY.get_sample_value(f"raven_{unlabelled_first}_total") == 2
    assert metrics.snapshot()[f"raven_{unlabelled_first}{{channel=webchat}}_total"] == 1, (
        "the collector lost the label it could keep"
    )


def test_a_latency_whose_calls_disagree_about_labels_counts_every_call() -> None:
    labelled_first = "gate_latency_labelled_first"
    metrics.observe(labelled_first, 0.42, {"provider": "ollama", "model": "ollama/llama3"})
    metrics.observe(labelled_first, 1.37)
    scraped = _mirror(f"raven_{labelled_first}_duration_seconds")
    assert scraped[f"raven_{labelled_first}_duration_seconds_count", (("model", ""), ("provider", ""))] == 1, (
        "the shape that arrived second never reached the mirror"
    )
    assert (
        scraped[f"raven_{labelled_first}_duration_seconds_count", (("model", "ollama/llama3"), ("provider", "ollama"))]
        == 1
    )

    unlabelled_first = "gate_latency_unlabelled_first"
    metrics.observe(unlabelled_first, 0.5)
    metrics.observe(unlabelled_first, 0.25, {"provider": "ollama"})
    assert (
        _mirror(f"raven_{unlabelled_first}_duration_seconds")[f"raven_{unlabelled_first}_duration_seconds_count", ()]
        == 2
    )


def test_a_dimension_the_mirror_cannot_hold_is_said_once() -> None:
    name = "gate_dropped_dimension"
    metrics.inc(name, {"x": "1"})
    records: list[str] = []
    sink = logger.add(records.append, level="WARNING", format="{message}")
    try:
        metrics.inc(name, {"x": "2", "y": "3"})
        metrics.inc(name, {"x": "4", "y": "5"})
    finally:
        logger.remove(sink)

    warnings = [record for record in records if name in record]
    assert len(warnings) == 1, f"expected one warning about the dropped dimension, got {warnings}"
    assert "y" in warnings[0]
    assert REGISTRY.get_sample_value(f"raven_{name}_total", {"x": "2"}) == 1
    assert REGISTRY.get_sample_value(f"raven_{name}_total", {"x": "4"}) == 1
    assert metrics.snapshot()[f"raven_{name}{{x=2,y=3}}_total"] == 1, "the collector lost a label it could keep"


def test_the_text_surface_is_what_a_prometheus_scrape_parses() -> None:
    collector = MetricsCollector()
    collector.inc("messages_received", {"channel": "webchat"})
    collector.inc("db_query")
    collector.observe("llm_request", 0.42, {"provider": "ollama", "model": "ollama/llama3"})
    collector.observe("llm_request", 1.37, {"provider": "ollama", "model": "ollama/llama3"})
    collector.error("rag_search", {"reason": 'a"b,c'})

    text = collector.prometheus()
    scraped = _scrape(text)
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert len(scraped) == len(lines), f"a scrape parsed {len(scraped)} of the {len(lines)} samples offered: {lines}"
    assert scraped["raven_messages_received_total", (("channel", "webchat"),)] == 1
    assert scraped["raven_db_query_total", ()] == 1
    assert scraped["raven_llm_request_count", (("model", "ollama/llama3"), ("provider", "ollama"))] == 2
    assert scraped["raven_llm_request_sum", (("model", "ollama/llama3"), ("provider", "ollama"))] == 1.79
    assert scraped["raven_rag_search_errors_total", (("reason", 'a"b,c'),)] == 1


def test_the_two_surfaces_of_one_collector_report_the_same_numbers() -> None:
    collector = MetricsCollector()
    collector.inc("messages_received", {"channel": "webchat"})
    collector.observe("llm_request", 0.5, {"provider": "ollama"})
    collector.error("rag_search", {"reason": "timeout"})
    snapshot = collector.snapshot()
    scraped = _scrape(collector.prometheus())

    assert (
        snapshot["raven_messages_received{channel=webchat}_total"]
        == scraped["raven_messages_received_total", (("channel", "webchat"),)]
    )
    assert (
        snapshot["raven_llm_request{provider=ollama}_sum"]
        == scraped["raven_llm_request_sum", (("provider", "ollama"),)]
    )
    assert (
        snapshot["raven_rag_search{reason=timeout}_errors_total"]
        == scraped["raven_rag_search_errors_total", (("reason", "timeout"),)]
    )


def test_the_collector_still_records_without_prometheus_installed(monkeypatch: MonkeyPatch) -> None:
    """`prometheus_client` is optional, and the console reads the collector rather than the mirror."""
    import raven.core.metrics as module

    monkeypatch.setattr(module, "HAS_PROMETHEUS", False)
    metrics.inc("gate_prometheus_absent", {"channel": "webchat"})
    assert metrics.snapshot()["raven_gate_prometheus_absent{channel=webchat}_total"] == 1
