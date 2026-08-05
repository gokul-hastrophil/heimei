import pytest
from loguru import logger

from heimei.logging.sinks.console import add_console_sink


@pytest.fixture(autouse=True)
def clean_loguru():
    logger.remove()
    yield
    logger.remove()


def test_add_console_sink_returns_an_int_id():
    sink_id = add_console_sink()

    assert isinstance(sink_id, int)


def test_console_sink_writes_to_stderr(capsys):
    add_console_sink(level="INFO")

    logger.bind(subsystem="runtime").info("Runtime started")

    captured = capsys.readouterr()
    assert "Runtime started" in captured.err
    assert "INFO" in captured.err
    assert captured.out == ""


def test_console_sink_respects_level_filter(capsys):
    add_console_sink(level="WARNING")

    logger.debug("should not appear")
    logger.warning("should appear")

    captured = capsys.readouterr()
    assert "should not appear" not in captured.err
    assert "should appear" in captured.err


def test_console_sink_removes_loguru_default_sink_to_avoid_duplicate_output(capsys):
    add_console_sink(level="INFO")

    logger.info("only once")

    captured = capsys.readouterr()
    assert captured.err.count("only once") == 1
