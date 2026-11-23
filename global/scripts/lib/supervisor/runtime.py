"""Where this copy of the tool is installed."""
import os

# The entry point (scripts/supervisor-lock), used to relaunch the tool and to find the hooks next to it.
ENTRY = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', '..', 'supervisor-lock'))
