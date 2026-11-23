#!/usr/bin/env python3
"""shipgate flow journal — an append-only SQLite event log.

Python 3 standard library only, no dependencies. See
``shipgate/docs/prd/journal.md`` and ``journal.worklog.md`` for the design.

Exit codes (also printed by ``--help``):

    0  ok
    1  infrastructure failure (db missing/unreadable, IO error, `position` on a
       stream with no events)
    2  usage error
    3  version conflict (conditional append lost the race)
    4  gate violation (an append's precondition is unmet)
    5  check findings (missing semantic events)
    6  import conflicts
"""

import os
import sys


def _load_package():
    """The modules of `_journal/`, loaded under a name no other load uses (ADR 0027)."""
    import importlib.util

    directory = os.path.join(os.path.dirname(os.path.realpath(__file__)), "_journal")
    index = 0
    while f"_shipgate_journal_{index}" in sys.modules:
        index += 1
    name = f"_shipgate_journal_{index}"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(directory, "__init__.py"),
        submodule_search_locations=[directory],
    )
    try:
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        spec.loader.exec_module(package)
    except (OSError, ImportError) as exc:
        sys.exit(f"error: cannot load {directory} (shipgate install incomplete): {exc}")
    return package


_package = _load_package()
globals().update(_package.names())


if __name__ == "__main__":
    sys.exit(main())
