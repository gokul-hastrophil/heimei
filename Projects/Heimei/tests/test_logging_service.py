import pytest
from loguru import logger

from heimei.logging.service import LoggingService


@pytest.fixture(autouse=True)
def clean_loguru():
    logger.remove()
    yield
    logger.remove()


@pytest.fixture
def captured():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    yield records
    logger.remove(sink_id)


def test_service_can_be_created_with_no_arguments():
    LoggingService()


@pytest.mark.parametrize(
    "method_name,level_name",
    [
        ("debug", "DEBUG"),
        ("info", "INFO"),
        ("warning", "WARNING"),
        ("error", "ERROR"),
        ("critical", "CRITICAL"),
    ],
)
def test_each_level_method_logs_at_the_right_level(captured, method_name, level_name):
    service = LoggingService()

    getattr(service, method_name)("hello")

    assert len(captured) == 1
    assert captured[0]["level"].name == level_name
    assert captured[0]["message"] == "hello"


def test_structured_fields_are_attached_to_the_record(captured):
    service = LoggingService()

    service.info("Runtime started", subsystem="runtime", manager="logging")

    (record,) = captured
    assert record["message"] == "Runtime started"
    assert record["extra"] == {"subsystem": "runtime", "manager": "logging"}


def test_no_fields_means_empty_extra(captured):
    service = LoggingService()

    service.warning("plain message")

    (record,) = captured
    assert record["extra"] == {}


def test_each_call_has_independent_fields(captured):
    service = LoggingService()

    service.info("first", request_id="a")
    service.info("second", request_id="b")

    first, second = captured
    assert first["extra"] == {"request_id": "a"}
    assert second["extra"] == {"request_id": "b"}
