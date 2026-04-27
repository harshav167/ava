"""MCP tools for browsing and exporting conversation exchange history."""

import json
from datetime import date as date_type, datetime
from typing import Literal

from ..server import mcp
from ..config import logger
from ..exchanges import (
    ConversationGrouper,
    ExchangeFilter,
    ExchangeFormatter,
    ExchangeReader,
    ExchangeStats,
)

Action = Literal["view", "search", "stats", "export"]
ExchangeType = Literal["all", "stt", "tts"]
StatsView = Literal[
    "summary",
    "timing",
    "providers",
    "transports",
    "conversations",
    "errors",
    "silence",
    "all",
]
ExchangeFormat = Literal["simple", "pretty", "json", "markdown", "csv", "html"]


def _parse_date(date_str: str | None) -> date_type | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("date must be in YYYY-MM-DD format") from exc


def _get_exchanges(
    reader: ExchangeReader,
    *,
    days: int | None,
    date_str: str | None,
    conversation_id: str | None,
    limit: int,
) -> list:
    if conversation_id:
        return reader.read_conversation(conversation_id)

    target_date = _parse_date(date_str)
    if target_date:
        return list(reader.read_date(target_date))

    if days is not None:
        return list(reader.read_recent(days))

    return reader.get_latest_exchanges(limit)


def _apply_common_filters(
    exchanges: list,
    *,
    exchange_type: ExchangeType,
    provider: str | None,
    transport: str | None,
    voice: str | None,
    project_path: str | None,
    has_error: bool,
    has_audio: bool,
) -> list:
    filter_obj = ExchangeFilter()
    filter_obj.by_type(exchange_type)

    if provider:
        filter_obj.by_provider(provider)
    if transport:
        filter_obj.by_transport(transport)
    if voice:
        filter_obj.by_voice(voice)
    if project_path:
        filter_obj.by_project(project_path)
    if has_error:
        filter_obj.has_error()
    if has_audio:
        filter_obj.has_audio()

    return list(filter_obj.apply(iter(exchanges)))


def _render_exchanges(exchanges: list, *, format: ExchangeFormat, limit: int) -> str:
    formatter = ExchangeFormatter()
    exchanges = exchanges[:limit]

    if not exchanges:
        return "No exchanges found."

    if format == "json":
        return json.dumps([exchange.to_dict() for exchange in exchanges], indent=2)

    if format == "csv":
        lines = [formatter.csv_header()]
        lines.extend(formatter.csv(exchange) for exchange in exchanges)
        return "\n".join(lines)

    if format == "markdown":
        grouped = ConversationGrouper().group_exchanges(exchanges)
        sections = [
            formatter.markdown(conv, include_metadata=True)
            for conv in grouped.values()
        ]
        return "\n\n---\n\n".join(sections)

    if format == "html":
        grouped = list(ConversationGrouper().group_exchanges(exchanges).values())
        if len(grouped) != 1:
            return "HTML output requires a single conversation/date selection."
        return formatter.html(grouped[0])

    if format == "pretty":
        return "\n\n".join(formatter.pretty(exchange) for exchange in exchanges)

    return "\n".join(formatter.simple(exchange, color=False) for exchange in exchanges)


def _render_stats(exchanges: list, stats_view: StatsView) -> str:
    if not exchanges:
        return "No exchanges found."

    stats = ExchangeStats(exchanges)

    if stats_view == "summary":
        return stats.get_summary_report()
    if stats_view == "timing":
        return json.dumps(stats.timing_stats(), indent=2)
    if stats_view == "providers":
        return json.dumps(
            {
                "providers": stats.provider_breakdown(),
                "models": stats.model_breakdown(),
                "voices": stats.voice_breakdown(),
            },
            indent=2,
        )
    if stats_view == "transports":
        return json.dumps(
            {
                "transport": stats.transport_breakdown(),
                "hourly": stats.hourly_distribution(),
                "daily": stats.daily_distribution(),
            },
            indent=2,
        )
    if stats_view == "conversations":
        return json.dumps(stats.conversation_stats(), indent=2)
    if stats_view == "errors":
        return json.dumps(stats.error_stats(), indent=2)
    if stats_view == "silence":
        return json.dumps(stats.silence_detection_stats(), indent=2)

    return json.dumps(
        {
            "summary": stats.get_summary_report(),
            "timing": stats.timing_stats(),
            "providers": stats.provider_breakdown(),
            "models": stats.model_breakdown(),
            "voices": stats.voice_breakdown(),
            "transport": stats.transport_breakdown(),
            "conversations": stats.conversation_stats(),
            "errors": stats.error_stats(),
            "silence": stats.silence_detection_stats(),
        },
        indent=2,
        default=str,
    )


@mcp.tool()
async def exchanges(
    action: Action = "view",
    query: str | None = None,
    days: int | None = None,
    date: str | None = None,
    conversation_id: str | None = None,
    exchange_type: ExchangeType = "all",
    format: ExchangeFormat = "simple",
    limit: int = 20,
    regex: bool = False,
    ignore_case: bool = True,
    show_conversation: bool = False,
    stats_view: StatsView = "summary",
    provider: str | None = None,
    transport: str | None = None,
    voice: str | None = None,
    project_path: str | None = None,
    has_error: bool = False,
    has_audio: bool = False,
    reverse: bool = False,
) -> str:
    """Browse, search, analyze, and export voice conversation exchange history.

    Actions:
    - view: show recent exchanges, a specific date, or a conversation
    - search: full-text search across recent history
    - stats: usage and timing analytics
    - export: structured export in json/csv/markdown/html
    """
    try:
        if limit < 1 or limit > 200:
            return "Error: limit must be between 1 and 200"
        if days is not None and days < 1:
            return "Error: days must be positive"

        reader = ExchangeReader()
        exchanges_data = _get_exchanges(
            reader,
            days=days,
            date_str=date,
            conversation_id=conversation_id,
            limit=limit,
        )
        exchanges_data = _apply_common_filters(
            exchanges_data,
            exchange_type=exchange_type,
            provider=provider,
            transport=transport,
            voice=voice,
            project_path=project_path,
            has_error=has_error,
            has_audio=has_audio,
        )

        if action == "search":
            if not query:
                return "Error: query is required for action='search'"
            search_filter = ExchangeFilter().by_text(
                query, regex=regex, ignore_case=ignore_case
            )
            matches = list(search_filter.apply(iter(exchanges_data)))
            if show_conversation:
                if not matches:
                    return "No exchanges found."
                groups = ConversationGrouper().group_exchanges(matches)
                conversations = list(groups.values())[:limit]
                if format == "json":
                    return json.dumps([conv.to_dict() for conv in conversations], indent=2)
                if format == "html":
                    if len(conversations) != 1:
                        return "HTML output requires a single matching conversation."
                    return ExchangeFormatter().html(conversations[0])
                sections = [
                    ExchangeFormatter().markdown(conv, include_metadata=True)
                    if format == "markdown"
                    else conv.to_transcript(include_timestamps=True)
                    for conv in conversations
                ]
                return "\n\n---\n\n".join(sections)
            return _render_exchanges(matches, format=format, limit=limit)

        if reverse:
            exchanges_data = list(reversed(exchanges_data))
        else:
            exchanges_data = sorted(exchanges_data, key=lambda e: e.timestamp, reverse=True)

        if action == "stats":
            return _render_stats(exchanges_data, stats_view)

        if action == "export":
            if format not in {"json", "csv", "markdown", "html"}:
                return "Error: export format must be one of json, csv, markdown, html"
            return _render_exchanges(exchanges_data, format=format, limit=limit)

        return _render_exchanges(exchanges_data, format=format, limit=limit)

    except ValueError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        logger.error(f"Error in exchanges tool: {exc}")
        return f"Error browsing exchanges: {exc}"
