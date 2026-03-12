from __future__ import annotations

import errno
import logging
import logging.handlers
import time


class SafeTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """Avoid noisy rollover failures on Windows when another process holds the log file."""

    _LOCK_WINERRORS = {13, 32}

    @classmethod
    def _is_lock_error(cls, exc: BaseException) -> bool:
        if not isinstance(exc, OSError):
            return False
        if isinstance(exc, PermissionError):
            return True
        if getattr(exc, "errno", None) == errno.EACCES:
            return True
        return getattr(exc, "winerror", None) in cls._LOCK_WINERRORS

    def _postpone_rollover(self) -> None:
        current_time = int(time.time())
        next_rollover = self.computeRollover(current_time)
        while next_rollover <= current_time:
            next_rollover += self.interval
        self.rolloverAt = next_rollover

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.shouldRollover(record):
                try:
                    self.doRollover()
                except Exception as exc:
                    if not self._is_lock_error(exc):
                        raise
                    self._postpone_rollover()
            logging.FileHandler.emit(self, record)
        except Exception as exc:
            if self._is_lock_error(exc):
                try:
                    if self.stream:
                        self.stream.close()
                except Exception:
                    pass
                self.stream = None
                self._postpone_rollover()
                try:
                    logging.FileHandler.emit(self, record)
                    return
                except Exception:
                    pass
            self.handleError(record)
