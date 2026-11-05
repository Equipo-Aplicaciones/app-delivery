#!/usr/bin/env python3
"""Punto de entrada: python3 refresh.py (SNAPSHOT_PATH y rutas CLI por env)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delivery_monitor.refresh import main

if __name__ == "__main__":
    raise SystemExit(main())
