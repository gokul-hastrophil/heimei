"""Independent, single-responsibility collectors for live machine state.

Each module exposes exactly one function, ``collect() -> SomeSnapshot``,
taking no arguments, and owns its own Snapshot model(s) in the same
file. Collectors never import each other and never import
``InventoryService`` or anything from ``heimei.core`` — see ADR-0013.

This is the only package in Heimei allowed to import ``psutil``,
``pynvml``, call ``platform.*``, or shell out to ``nvidia-smi``/
``lspci``/``docker`` directly.

Extension point: each collector is a platform-specific implementation
behind the stable ``collect()`` contract. ``InventoryService`` and every
consumer call collectors only by import path and never inspect how a
collector gets its answer, so a collector's internals can be swapped
(e.g. split into per-OS implementations) without changing
``InventoryService``. No such split exists yet — see ADR-0013, Decision
section 4.
"""
