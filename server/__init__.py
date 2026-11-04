"""Prism application server — persistence, services, HTTP API and CLI.

The engine packages (``core``, ``data``, ``presentation``, ``catalog``)
are pure libraries. Everything stateful — the metadata database, the
dataset store on disk, authentication, licensing and the REST API —
lives here, so the engine stays testable without I/O.
"""

__version__ = "1.0.0"
