"""The journal's modules, in layer order (ADR 0027): each imports only the ones before it.

`journal.py` loads this package by path and copies `names()` into its own namespace.
"""

from . import (
    vocab, plugin, text, project, settings, store, sessions, approval, fold, artifacts,
    shapes, screens, runs, gates, append, status, reply, check, position, handoff,
    closeout, stats, doctor, transfer, assumptions, digest, cli,
)

_LAYERS = (
    vocab, plugin, text, project, settings, store, sessions, approval, fold, artifacts,
    shapes, screens, runs, gates, append, status, reply, check, position, handoff,
    closeout, stats, doctor, transfer, assumptions, digest, cli,
)


def names():
    """Every top-level name of every module, dunder names excluded; a later module wins."""
    out = {}
    for module in _LAYERS:
        out.update((k, v) for k, v in vars(module).items()
                   if not (k.startswith("__") and k.endswith("__")))
    return out
