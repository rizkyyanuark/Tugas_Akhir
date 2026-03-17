"""
Professional logging infrastructure using loguru.

Provides dual-output logging (console + file) with context tracking,
log sampling, and automatic rotation for the UNESA Dosen Pipeline.
"""

from loguru import logger
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
import random


class PipelineLogger:
    """
    Centralized logging with dual output (console + file) and context tracking.

    Features:
    - Console output: INFO+, user-friendly format
    - File output: DEBUG+, detailed with function/line info
    - Context tracking: phase, prodi, record_id for tracing
    - Log sampling: Configurable rate to prevent log explosion
    - Automatic rotation: 100MB files, 30-day retention, gzip compression

    Attributes:
        log_dir (Path): Directory for log files
        enable_record_level (bool): Whether to log individual records
        sampling_rate (float): Fraction of records to log (0.0-1.0)
        logger: Bound loguru logger instance
    """

    def __init__(
        self,
        log_dir: Path,
        log_level: str = "INFO",
        enable_record_level: bool = False,
        log_sampling_rate: float = 0.1
    ):
        """
        Initialize the pipeline logger.

        Args:
            log_dir: Directory to store log files
            log_level: Console logging level (DEBUG/INFO/WARNING/ERROR)
            enable_record_level: Enable detailed record-level logging
            log_sampling_rate: Fraction of records to log (0.0-1.0)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.enable_record_level = enable_record_level
        self.sampling_rate = log_sampling_rate
        self.trace_records = set()  # Specific record IDs to always log

        # Remove default logger
        logger.remove()

        # Console Handler (Clean, emoji-free, user-friendly)
        logger.add(
            sys.stdout,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{extra[phase]: <25}</cyan> | "
                "{message}"
            ),
            level=log_level,
            colorize=True,
            filter=lambda record: "phase" in record["extra"]
        )

        # File Handler (Detailed, with function/line info for debugging)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"pipeline_{timestamp}.log"
        logger.add(
            log_file,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                "{level: <8} | "
                "{extra[phase]: <25} | "
                "{extra[prodi]: <35} | "
                "{extra[record_id]: <10} | "
                "{message}"
            ),
            level="DEBUG",  # File gets ALL details
            rotation="100 MB",
            retention="30 days",
            compression="zip",
            filter=lambda record: "phase" in record["extra"]
        )

        # Bind default context
        self.logger = logger.bind(phase="INIT", prodi="N/A", record_id="N/A")
        self.logger.info(f"Logging initialized. Log file: {log_file}")
        self.logger.info(f"Configuration: level={log_level}, record_logging={enable_record_level}, sampling={log_sampling_rate:.0%}")

    def get_logger(
        self,
        phase: str,
        prodi: str = "N/A",
        record_id: str = "N/A"
    ):
        """
        Get a context-bound logger for a specific phase/prodi/record.

        Args:
            phase: Pipeline phase name (e.g., "PHASE_1_PDDIKTI")
            prodi: Program studi name (e.g., "S1 Teknik Informatika")
            record_id: Record identifier for tracing (e.g., "12" or "agus_prihanto")

        Returns:
            Bound logger instance with context
        """
        return self.logger.bind(phase=phase, prodi=prodi, record_id=record_id)

    def should_log_record(self, record_id: str, is_failure: bool = False) -> bool:
        """
        Determine if a record should be logged based on sampling strategy.

        Always logs:
        - Failures/warnings
        - Records in trace_records set
        - When enable_record_level is True

        Sampled logging:
        - Regular successful operations based on sampling_rate

        Args:
            record_id: Record identifier (used for consistent sampling)
            is_failure: Whether this is an error/warning condition

        Returns:
            True if record should be logged
        """
        # Always log failures
        if is_failure:
            return True

        # Always log traced records
        if record_id in self.trace_records:
            return True

        # If record logging disabled, skip
        if not self.enable_record_level:
            return False

        # Sample based on rate
        if self.sampling_rate >= 1.0:
            return True

        # Consistent sampling using hash
        return (hash(record_id) % 100) < (self.sampling_rate * 100)

    def enable_trace(self, record_ids: list):
        """
        Enable full logging for specific records (for debugging).

        Args:
            record_ids: List of record IDs to trace through pipeline
        """
        self.trace_records.update(str(rid).lower().strip() for rid in record_ids)
        self.logger.info(f"Trace mode enabled for {len(record_ids)} records: {list(self.trace_records)}")

    def log_record_event(
        self,
        phase_logger,
        record_id: str,
        name: str,
        event: str,
        status: str,
        details: Optional[str] = None
    ):
        """
        Log a record-level event with sampling.

        Args:
            phase_logger: Logger instance for the current phase
            record_id: Record identifier
            name: Record name (e.g., lecturer name)
            event: Event type (e.g., "MATCH", "ENRICH", "SKIP")
            status: Status (e.g., "SUCCESS", "FAILED", "WARNING")
            details: Optional additional details
        """
        is_failure = status in ["FAILED", "WARNING", "ERROR"]

        if self.should_log_record(record_id, is_failure):
            msg = f"Record #{record_id} ({name}): {event} - {status}"
            if details:
                msg += f" | {details}"

            if status == "FAILED" or status == "ERROR":
                phase_logger.error(msg)
            elif status == "WARNING":
                phase_logger.warning(msg)
            else:
                phase_logger.debug(msg)


def setup_logger(
    log_dir: str = "logs",
    log_level: str = "INFO",
    enable_record_logging: bool = False,
    log_sampling_rate: float = 0.1
) -> PipelineLogger:
    """
    Convenience function to set up the pipeline logger.

    Args:
        log_dir: Directory for log files (default: "logs")
        log_level: Console logging level
        enable_record_logging: Enable detailed record-level logging
        log_sampling_rate: Fraction of records to log

    Returns:
        Configured PipelineLogger instance
    """
    return PipelineLogger(
        log_dir=Path(log_dir),
        log_level=log_level,
        enable_record_level=enable_record_logging,
        log_sampling_rate=log_sampling_rate
    )
