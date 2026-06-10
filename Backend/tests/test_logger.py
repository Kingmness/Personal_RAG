# -*- coding: utf-8 -*-
import logging
import time
from pathlib import Path

from logger import setup_logger, _clean_old_logs


class TestSetupLogger:
    def test_returns_logger(self):
        logger = setup_logger(name="test.setup", log_to_file=False)
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.setup"

    def test_no_duplicate_handlers(self):
        name = "test.dedup"
        logging.getLogger(name).handlers.clear()
        logger1 = setup_logger(name=name, log_to_file=False)
        count1 = len(logger1.handlers)
        logger2 = setup_logger(name=name, log_to_file=False)
        assert len(logger2.handlers) == count1

    def test_file_handler_created(self, tmp_path):
        name = "test.file_handler"
        logging.getLogger(name).handlers.clear()
        log_dir = tmp_path / "logs"
        logger = setup_logger(name=name, log_dir=log_dir, log_to_file=True)
        assert log_dir.exists()
        has_file_handler = any(
            isinstance(h, logging.handlers.RotatingFileHandler)
            for h in logger.handlers
        )
        assert has_file_handler


class TestCleanOldLogs:
    def test_removes_old_logs(self, tmp_path):
        old_file = tmp_path / "old.log"
        old_file.write_text("old content")

        import os
        old_time = time.time() - 10 * 86400
        os.utime(old_file, (old_time, old_time))

        new_file = tmp_path / "new.log"
        new_file.write_text("new content")

        _clean_old_logs(tmp_path, max_age_days=7)

        assert not old_file.exists()
        assert new_file.exists()

    def test_skips_non_log_files(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        import os
        old_time = time.time() - 10 * 86400
        csv_file.write_text("data")
        os.utime(csv_file, (old_time, old_time))

        _clean_old_logs(tmp_path, max_age_days=7)
        assert csv_file.exists()
