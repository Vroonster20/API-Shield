"""Run operator commands from the repository root: python backend/manage.py migrate."""

from shield_api.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
