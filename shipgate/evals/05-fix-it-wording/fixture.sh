#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
cat > dates.py <<'PY'
from datetime import datetime, timedelta, timezone


def parse_date(stamp, utc_offset_hours):
    """Calendar date the user sees for a local timestamp in their own UTC offset."""
    local = datetime.fromisoformat(stamp).replace(tzinfo=timezone(timedelta(hours=utc_offset_hours)))
    return local.date()
PY
cat > test_dates.py <<'PY'
import unittest
from datetime import date

from dates import parse_date


class ParseDateTest(unittest.TestCase):
    def test_morning_in_berlin(self):
        self.assertEqual(parse_date("2026-03-10T10:00:00", 1), date(2026, 3, 10))

    def test_evening_in_new_york(self):
        self.assertEqual(parse_date("2026-03-10T22:00:00", -5), date(2026, 3, 10))

    def test_early_morning_in_tokyo(self):
        self.assertEqual(parse_date("2026-03-10T06:00:00", 9), date(2026, 3, 10))


if __name__ == "__main__":
    unittest.main()
PY
c 2026-09-09 "feat: parse_date for user-local timestamps"
printf '# dates\n\nRun tests: `python3 -m unittest`\n' > README.md
c 2026-09-11 "docs: add README"
python3 - <<'PY'
s = open("dates.py").read()
s = s.replace("    return local.date()", "    return local.astimezone(timezone.utc).date()")
open("dates.py", "w").write(s)
PY
c 2026-09-17 "refactor: normalize timestamps to UTC"
