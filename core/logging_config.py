from __future__ import annotations

import io
import logging
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO


_HANDLER_MARKER = "_wulf_forge_file_handler"


def _unique_log_file(log_path: Path) -> Path:
    """Return a boot log path that does not collide at coarse clock resolution."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    stem = f"wulf-forge-{timestamp}-{os.getpid()}"
    candidate = log_path / f"{stem}.log"
    suffix = 1
    while candidate.exists():
        candidate = log_path / f"{stem}-{suffix}.log"
        suffix += 1
    return candidate


class TeeLoggingStream(io.TextIOBase):
    """Mirror writes to the original stream and line-buffer them into logging."""

    def __init__(self, stream: TextIO, logger: logging.Logger, level: int):
        self._stream = stream
        self._logger = logger
        self._level = level
        self._buffer = ""
        self._lock = threading.RLock()

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8")

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return bool(getattr(self._stream, "isatty", lambda: False)())

    def write(self, text: str) -> int:
        if not text:
            return 0

        with self._lock:
            self._stream.write(text)
            self._stream.flush()
            self._buffer += text

            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._emit(line)

        return len(text)

    def flush(self) -> None:
        with self._lock:
            self._stream.flush()
            if self._buffer:
                self._emit(self._buffer)
                self._buffer = ""

    def _emit(self, line: str) -> None:
        line = line.rstrip("\r")
        if line:
            self._logger.log(self._level, line)


@dataclass(frozen=True, slots=True)
class LoggingRuntime:
    log_file: Path
    original_stdout: TextIO
    original_stderr: TextIO

    def restore(self) -> None:
        sys.stdout.flush()
        sys.stderr.flush()
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, _HANDLER_MARKER, False):
                root.removeHandler(handler)
                handler.close()


def setup_logging(
    log_dir: str | os.PathLike[str] = "logs",
    *,
    install_stream_redirect: bool = True,
) -> LoggingRuntime:
    """
    Configure file logging for one server boot.

    Existing print-based diagnostics are captured by teeing stdout/stderr into
    named loggers. Each call creates a fresh timestamped log file.
    """
    log_path = Path(log_dir).resolve()
    log_path.mkdir(parents=True, exist_ok=True)

    log_file = _unique_log_file(log_path)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    setattr(file_handler, _HANDLER_MARKER, True)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(file_handler)

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    if install_stream_redirect:
        sys.stdout = TeeLoggingStream(
            original_stdout,
            logging.getLogger("wulf_forge.stdout"),
            logging.INFO,
        )
        sys.stderr = TeeLoggingStream(
            original_stderr,
            logging.getLogger("wulf_forge.stderr"),
            logging.ERROR,
        )

    logging.getLogger("wulf_forge").info("Logging initialized: %s", log_file)

    return LoggingRuntime(
        log_file=log_file,
        original_stdout=original_stdout,
        original_stderr=original_stderr,
    )
