"""
Exchange writer for voice mode conversation logs.

The writer owns the JSONL file layout while the Exchange model owns the
serialized record shape. This keeps producers and readers on the same contract.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Optional, Union

from voice_mode.config import BASE_DIR
from voice_mode.exchanges.models import Exchange, exchange_log_filename


class ExchangeWriter:
    """Append exchange records to the shared JSONL log layout."""

    def __init__(self, logs_dir: Optional[Path] = None):
        """Initialize writer with the conversations log directory.

        Args:
            logs_dir: Directory containing exchanges_YYYY-MM-DD.jsonl files.
                Defaults to ~/.voicemode/logs/conversations/.
        """
        self.logs_dir = (
            Path(logs_dir) if logs_dir else Path(BASE_DIR) / "logs" / "conversations"
        )
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def get_log_file_path(self, target_date: Union[date, datetime]) -> Path:
        """Get the JSONL file path for a date using the shared filename layout."""
        if isinstance(target_date, datetime):
            target_date = target_date.date()

        return self.logs_dir / exchange_log_filename(target_date)

    def append(self, exchange: Exchange) -> Path:
        """Append an exchange and return the file that was written."""
        log_file = self.get_log_file_path(exchange.timestamp)
        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write(exchange.to_jsonl() + "\n")
        return log_file
