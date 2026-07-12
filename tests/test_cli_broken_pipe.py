"""CLI must not crash when a downstream reader closes the pipe early (#1807).

Truncating a command's output (`head`, PowerShell `Select-Object -First N`,
`sed q`) is routine. graphify used to keep writing after the reader disconnected,
hit an unhandled BrokenPipeError, and exit 255 — so CI wrappers and agent
harnesses that both trim output and check the exit code read a successful query
as a failure. An early-closing reader is now treated as success (exit 0).
"""
from __future__ import annotations

import subprocess
import sys

PYTHON = sys.executable


def test_help_survives_reader_closing_pipe_early():
    """`graphify --help | head -n1` must leave graphify exiting 0, not 255."""
    producer = subprocess.Popen(
        [PYTHON, "-m", "graphify", "--help"], stdout=subprocess.PIPE
    )
    reader = subprocess.Popen(
        [PYTHON, "-c", "import sys; sys.stdin.readline()"],
        stdin=producer.stdout,
        stdout=subprocess.DEVNULL,
    )
    producer.stdout.close()  # let the producer see EPIPE when the reader exits
    reader.wait()
    rc = producer.wait()
    # 0 (our handled-and-succeed convention). Never the 255 unhandled-exception code.
    assert rc == 0, f"expected clean exit after early pipe close, got {rc}"
