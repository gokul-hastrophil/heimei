from datetime import UTC, datetime

from heimei.inventory.record import InventoryRecord


def test_record_holds_required_metadata():
    record = InventoryRecord(
        collected_at=datetime.now(UTC), source="test", collector_version="1.0"
    )

    assert record.source == "test"
    assert record.collector_version == "1.0"
    assert record.collected_at.tzinfo is not None


def test_snapshot_models_inherit_the_record_fields():
    from heimei.inventory.collectors.machine import MachineSnapshot

    assert issubclass(MachineSnapshot, InventoryRecord)
