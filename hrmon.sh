#!/bin/sh
# Launch HRMon from its project venv (no activation needed)
cd "$(dirname "$(readlink -f "$0")")" && exec .venv/bin/python -m hrmon "$@"
