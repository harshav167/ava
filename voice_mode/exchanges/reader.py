"""
Exchange reader for voice mode conversation logs.
"""

import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Iterator, List, Optional, Union, Dict
import subprocess

from voice_mode.exchanges.models import Exchange, exchange_log_filename
from voice_mode.config import BASE_DIR


logger = logging.getLogger(__name__)


class ExchangeReader:
    """Read and parse exchange JSONL files."""
    
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        logs_dir: Optional[Path] = None,
    ):
        """Initialize reader with the shared conversation log directory.

        Args:
            base_dir: Base directory for logs. Defaults to ~/.voicemode.
            logs_dir: Directory containing exchanges_YYYY-MM-DD.jsonl files.
                Use when the caller already owns the conversation log path.
        """
        if logs_dir is not None:
            self.logs_dir = Path(logs_dir)
            self.base_dir = self.logs_dir.parent.parent
        else:
            self.base_dir = Path(base_dir) if base_dir else Path(BASE_DIR)
            self.logs_dir = self.base_dir / "logs" / "conversations"

        # Ensure logs directory exists
        self.logs_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_log_file_path(self, date: Union[date, datetime]) -> Path:
        """Get the log file path for a given date."""
        if isinstance(date, datetime):
            date = date.date()
        
        return self.logs_dir / exchange_log_filename(date)
    
    def read_date(self, target_date: Union[date, datetime]) -> Iterator[Exchange]:
        """Read exchanges for a specific date.
        
        Args:
            target_date: Date to read exchanges for
            
        Yields:
            Exchange objects from that date
        """
        log_file = self._get_log_file_path(target_date)
        
        if not log_file.exists():
            logger.debug(f"No log file found for {target_date}")
            return
        
        yield from self._read_file(log_file)
    
    def read_range(self, start: datetime, end: datetime) -> Iterator[Exchange]:
        """Read exchanges in date range.
        
        Args:
            start: Start datetime (inclusive)
            end: End datetime (inclusive)
            
        Yields:
            Exchange objects within the date range
        """
        current_date = start.date()
        end_date = end.date()
        
        while current_date <= end_date:
            for exchange in self.read_date(current_date):
                # Filter by exact timestamp
                if start <= exchange.timestamp <= end:
                    yield exchange
            
            current_date += timedelta(days=1)
    
    def read_conversation(self, conversation_id: str) -> List[Exchange]:
        """Read all exchanges for a conversation.
        
        This searches through all log files to find exchanges with the
        matching conversation ID.
        
        Args:
            conversation_id: Conversation ID to search for
            
        Returns:
            List of exchanges for that conversation
        """
        exchanges = []
        
        # Search all log files
        for log_file in sorted(self.logs_dir.glob("exchanges_*.jsonl")):
            for exchange in self._read_file(log_file):
                if exchange.conversation_id == conversation_id:
                    exchanges.append(exchange)
        
        return exchanges
    
    def tail(self, follow: bool = True, lines: int = 0) -> Iterator[Exchange]:
        """Tail exchanges in real-time.
        
        Args:
            follow: Whether to follow the file for new entries
            lines: Number of recent lines to show first (0 for all)
            
        Yields:
            Exchange objects as they appear
        """
        today_file = self._get_log_file_path(datetime.now())
        
        if follow:
            # Use tail -f for real-time following
            cmd = ["tail", "-n", str(lines) if lines > 0 else "+1", "-f", str(today_file)]
            
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                
                for line in process.stdout:
                    exchange = self._parse_line(line)
                    if exchange is not None:
                        yield exchange
            
            except KeyboardInterrupt:
                process.terminate()
                process.wait()
            except Exception as e:
                logger.error(f"Error tailing file: {e}")
        else:
            # Just read the file once
            if today_file.exists():
                exchanges = list(self._read_file(today_file))
                
                # Return last N lines if specified
                if lines > 0 and len(exchanges) > lines:
                    exchanges = exchanges[-lines:]
                
                yield from exchanges
    
    def read_recent(self, days: int = 7) -> Iterator[Exchange]:
        """Read exchanges from recent days.
        
        Args:
            days: Number of days to look back
            
        Yields:
            Exchange objects from recent days
        """
        from datetime import timezone
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        yield from self.read_range(start_date, end_date)
    
    def get_all_conversations(self, days: Optional[int] = None) -> Dict[str, List[Exchange]]:
        """Get all conversations grouped by ID.
        
        Args:
            days: Number of days to look back (None for all)
            
        Returns:
            Dictionary mapping conversation IDs to their exchanges
        """
        from collections import defaultdict
        conversations = defaultdict(list)
        
        if days is not None:
            exchanges = self.read_recent(days)
        else:
            # Read all log files
            exchanges = self._read_all()
        
        for exchange in exchanges:
            conversations[exchange.conversation_id].append(exchange)
        
        return dict(conversations)
    
    def _read_file(self, file_path: Path) -> Iterator[Exchange]:
        """Read exchanges from a single file.

        Args:
            file_path: Path to the JSONL file

        Yields:
            Exchange objects from the file
        """
        if not file_path.exists():
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    exchange = self._parse_line(line, file_path=file_path, line_num=line_num)
                    if exchange is not None:
                        yield exchange

        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")

    def _parse_line(
        self,
        line: str,
        *,
        file_path: Optional[Path] = None,
        line_num: Optional[int] = None,
    ) -> Optional[Exchange]:
        """Parse one JSONL row, returning None for blank or malformed rows."""
        line = line.strip()
        if not line:
            return None

        location = ""
        if file_path is not None and line_num is not None:
            location = f" {line_num} in {file_path}"

        try:
            return Exchange.from_jsonl(line)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse line{location}: {e}")
        except Exception as e:
            logger.error(f"Error processing line{location}: {e}")

        return None
    
    def read_all(self) -> Iterator[Exchange]:
        """Read all exchanges from all log files in chronological file order."""
        yield from self._read_all()

    def _read_all(self) -> Iterator[Exchange]:
        """Read all exchanges from all log files.
        
        Yields:
            All exchanges in chronological order
        """
        # Get all log files sorted by date
        log_files = sorted(self.logs_dir.glob("exchanges_*.jsonl"))
        
        for log_file in log_files:
            yield from self._read_file(log_file)
    
    def read_latest_from_dates(
        self, dates: List[Union[date, datetime]]
    ) -> Optional[Exchange]:
        """Return the latest valid exchange from the first matching dated logs."""
        for target_date in dates:
            exchanges = list(self.read_date(target_date))
            if exchanges:
                return exchanges[-1]

        return None

    def get_latest_exchanges(self, count: int = 20) -> List[Exchange]:
        """Get the latest N exchanges.
        
        Args:
            count: Number of exchanges to return
            
        Returns:
            List of the most recent exchanges
        """
        # Read from today and work backwards if needed
        exchanges = []
        current_date = datetime.now().date()
        
        while len(exchanges) < count:
            # Try to read from current date
            daily_exchanges = list(self.read_date(current_date))
            
            if daily_exchanges:
                # Add to beginning since we're going backwards
                exchanges = daily_exchanges + exchanges
                
                # Trim to requested count
                if len(exchanges) > count:
                    exchanges = exchanges[-count:]
            
            # Go to previous day
            current_date -= timedelta(days=1)
            
            # Stop if we've gone back too far (e.g., 30 days)
            if (datetime.now().date() - current_date).days > 30:
                break
        
        return exchanges