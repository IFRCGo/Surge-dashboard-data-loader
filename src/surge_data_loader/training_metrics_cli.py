from __future__ import annotations

import argparse
import sys

from .config import load_dotenv, training_metrics_config_from_env
from .training_metrics import run_training_metrics_fetch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch sanitized RRMS staging training metrics JSON."
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Skip rewriting output files when the fetched metrics payload is unchanged.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print fetch progress.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    load_dotenv()
    try:
        config = training_metrics_config_from_env()
        manifest = run_training_metrics_fetch(
            config,
            verbose=args.verbose,
            incremental=args.incremental,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.verbose:
        print(
            f"Wrote training metrics to {manifest['output_file']} "
            f"({manifest['top_level_type']}, count={manifest['top_level_count']}, "
            f"output_written={manifest['output_written']}).",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
