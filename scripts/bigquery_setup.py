"""Create the BigQuery dataset and table that hold the audit trail.

    python scripts/bigquery_setup.py PROJECT              # bob_forecaster.audit_events
    python scripts/bigquery_setup.py PROJECT --no-expiry  # once billing is enabled

Idempotent: what exists is left as it is. Uses the same credentials as the
server (api/bigquery_audit.credentials). Prints the settings the server needs.

Without billing the project is in BigQuery's sandbox. That is enough -- the
server writes with load jobs and reads with tabledata.list, both free -- but
every table expires within 60 days; the server keeps moving the expiry
forward while it runs. With billing, --no-expiry removes it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import bigquery_audit as bq  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("project")
    parser.add_argument("--dataset", default="bob_forecaster")
    parser.add_argument("--table", default="audit_events")
    parser.add_argument("--location", default="asia-south1",
                        help="where the data is kept; Cloud Run's region in DEPLOY.md")
    parser.add_argument("--no-expiry", action="store_true",
                        help="remove the table's expiry (needs billing)")
    args = parser.parse_args(argv)

    table = bq.Table(f"{args.project}.{args.dataset}.{args.table}", bq.authorised_session())
    what = "Bay of Bengal cyclone forecaster"
    if table.ensure_dataset(args.location, f"{what}: the approval and dispatch audit trail"):
        print(f"created dataset {args.dataset} in {args.location}")
    if table.get() is None:
        table.create(f"{what}: every approval, withdrawal and dispatch attempt, append-only")
        print(f"created table {args.dataset}.{args.table}")
    if args.no_expiry:
        table.clear_expiry()
        print("expiry removed")
    expires = table.keep_alive(datetime.now(UTC))
    print("expires:", expires.date().isoformat() + " (sandbox; the server moves this forward)"
          if expires else "never")
    print("\nServer settings:\n  BOB_AUDIT_STORE=bigquery\n"
          f"  BOB_BQ_AUDIT_TABLE={args.project}.{args.dataset}.{args.table}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
