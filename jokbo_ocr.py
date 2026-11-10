"""Backward-compatible command-line entry point for the OCR pipeline."""

from ocr.pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
