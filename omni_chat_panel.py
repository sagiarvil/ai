#!/usr/bin/env python3
"""Compatibility import: every supported web entry point uses the durable runtime."""
from durable_api import app

if __name__ == '__main__':
    from baris_local import main
    main()
