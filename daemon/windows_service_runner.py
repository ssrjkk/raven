"""Entry point for Windows Service — called by pywin32's ServiceFramework."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daemon import run_gateway

if __name__ == "__main__":
    run_gateway()
