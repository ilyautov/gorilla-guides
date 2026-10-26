#!/bin/bash
# HF_HUB_OFFLINE: модель распознавания берётся из локального кэша, в интернет за ней не ходим.
cd "$(dirname "$0")" && HF_HUB_OFFLINE=1 exec .venv/bin/python kolonka.py "$@"
