from __future__ import annotations

import argparse
import sys

from .config import config_from_env, load_dotenv
from .runner import run_loader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build sanitized Power BI JSON from RRMS/Molnix event data."
    )
    page_group = parser.add_mutually_exclusive_group()
    page_group.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Maximum event pages to fetch. Defaults to 1 for safer local smoke tests.",
    )
    page_group.add_argument(
        "--all-pages",
        action="store_true",
        help="Fetch all available event pages.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print fetch progress.")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Merge new or updated events into the existing Power BI JSON and stop after known pages.",
    )
    parser.add_argument(
        "--person-workers",
        type=int,
        default=None,
        help="Concurrent workers for person tag/detail enrichment. Defaults to RRMS_PERSON_WORKERS or 4.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_pages is not None and args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    if args.person_workers is not None and args.person_workers < 1:
        parser.error("--person-workers must be at least 1")

    load_dotenv()
    try:
        config = config_from_env()
        if args.person_workers is not None:
            config = config.__class__(**{**config.__dict__, "person_workers": args.person_workers})
        manifest = run_loader(
            config,
            max_pages=None if args.all_pages else args.max_pages,
            all_pages=args.all_pages,
            incremental=args.incremental,
            verbose=args.verbose,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.verbose:
        print(
            "Wrote "
            f"{manifest['events_processed']} events and "
            f"{manifest['participant_links_written_inside_events']} participant links.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
