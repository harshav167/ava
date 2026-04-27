"""Tests for voice_mode.statistics."""

from voice_mode.statistics import ConversationMetric, ConversationStatistics


def test_export_metrics_returns_without_deadlock():
    stats = ConversationStatistics()
    stats.add_metric(
        ConversationMetric(
            timestamp=1.0,
            message="hello",
            response="world",
            total_time=2.0,
        )
    )

    exported = stats.export_metrics()

    assert exported["statistics"]["total_interactions"] == 1
    assert exported["metrics"][0]["message"] == "hello"
