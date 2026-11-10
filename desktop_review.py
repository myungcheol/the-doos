"""Backward-compatible command-line entry point for the desktop review app."""

from review.desktop import main


if __name__ == "__main__":
    raise SystemExit(main())
