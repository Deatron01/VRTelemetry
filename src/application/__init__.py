# src/application/__init__.py
"""Use cases and the ports they depend on (VRT-14).

The layer the target architecture has been missing. ``domain/`` holds entities
with no I/O; ``infrastructure/`` holds the things that talk to disks, sockets
and headsets. This is what sits between them: the ports that say *what* the
application needs, expressed without naming *who* provides it.

Nothing here may import from ``src.infrastructure`` or ``src.interfaces``.
Dependencies point inward.
"""
