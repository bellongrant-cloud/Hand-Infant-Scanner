"""Command-line interface: run the ridge-count pipeline on a scanner image."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import run_ridge_count
from .visualize import render_annotation


def _parse_point(s: str) -> tuple[int, int]:
    try:
        x_str, y_str = s.split(",")
        return int(x_str), int(y_str)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected 'X,Y', got {s!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ridge-count",
        description=(
            "Compute a dermatoglyphic ridge count (core-to-delta) from a "
            "fingerprint/palm scanner image."
        ),
    )
    parser.add_argument("image", help="Path to the scanner image (PNG/BMP/TIFF/JPEG).")
    parser.add_argument(
        "--core", type=_parse_point, default=None,
        help="Core point as X,Y pixel coords. Auto-detected if omitted.",
    )
    parser.add_argument(
        "--delta", type=_parse_point, default=None,
        help="Delta (triradius) point as X,Y pixel coords. Auto-detected if omitted.",
    )
    parser.add_argument("--block-size", type=int, default=16, help="Orientation-field block size in px.")
    parser.add_argument("--band-half-width", type=int, default=1, help="Sampling band half-width in px.")
    parser.add_argument("--exclude-px", type=float, default=0.0, help="Px to exclude at each line endpoint.")
    parser.add_argument("--output-dir", default=None, help="Directory to write annotated image + JSON report.")
    parser.add_argument("--json", action="store_true", help="Print result as JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = run_ridge_count(
            args.image,
            core=args.core,
            delta=args.delta,
            block_size=args.block_size,
            band_half_width=args.band_half_width,
            exclude_px=args.exclude_px,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)

    report = {
        "ridge_count": result.count,
        "core": result.core,
        "delta": result.delta,
        "core_confidence": result.core_confidence,
        "delta_confidence": result.delta_confidence,
        "crossings": result.crossings,
    }

    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        render_annotation(args.image, result, str(out_dir / "annotated.png"))
        with open(out_dir / "report.json", "w") as f:
            json.dump(report, f, indent=2)
        print(f"wrote {out_dir / 'annotated.png'} and {out_dir / 'report.json'}")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Ridge count: {result.count}")
        print(f"Core: {result.core}  Delta: {result.delta}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
