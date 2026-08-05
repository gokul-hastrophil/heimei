import json

import pytest
from loguru import logger

from heimei.logging.sinks.file import add_file_sink


@pytest.fixture(autouse=True)
def clean_loguru():
    logger.remove()
    yield
    logger.remove()


def test_add_file_sink_returns_an_int_id(tmp_path):
    sink_id = add_file_sink(tmp_path / "heimei.log")

    assert isinstance(sink_id, int)


def test_file_sink_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "heimei.log"

    add_file_sink(path)
    logger.info("hello")

    assert path.exists()


def test_file_sink_writes_structured_json_lines(tmp_path):
    path = tmp_path / "heimei.log"
    add_file_sink(path)

    logger.bind(manager="logging").info("Runtime started")

    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])["record"]
    assert record["message"] == "Runtime started"
    assert record["level"]["name"] == "INFO"
    assert record["extra"] == {"manager": "logging"}


def test_file_sink_respects_level_filter(tmp_path):
    path = tmp_path / "heimei.log"
    add_file_sink(path, level="ERROR")

    logger.info("filtered out")
    logger.error("kept")

    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["record"]["message"] == "kept"


def test_multiple_records_append_as_separate_lines(tmp_path):
    path = tmp_path / "heimei.log"
    add_file_sink(path)

    logger.info("first")
    logger.info("second")

    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
