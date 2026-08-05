from datetime import datetime

from pydantic import BaseModel


class InventoryRecord(BaseModel):
    """Shared metadata every inventory snapshot carries. See ADR-0013.

    Lets a consumer (Doctor, Status, a future monitor) judge freshness
    for itself; Inventory has no opinion about what "stale" means.
    """

    collected_at: datetime
    source: str
    collector_version: str
