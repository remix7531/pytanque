"""
Shared fixtures and utilities for Pytanque tests.

This module contains common fixtures and helper functions used across
both unit tests and integration tests.
"""

import pytest
import logging
import signal
import subprocess
import time
import socket
import os
from typing import Generator

from pytanque import Pytanque


# Configure logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_shared")


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is open and accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.error, ConnectionRefusedError, OSError):
        return False


# How long to wait for pet-server to accept connections. It loads the Rocq
# stdlib on startup, which is slow on a cold or busy machine.
STARTUP_TIMEOUT = 60


def _terminate(process: subprocess.Popen, sig: int = signal.SIGTERM) -> None:
    """Signal the whole process group, falling back to the process itself.

    pet-server is started with os.setsid, so signalling only the leader can
    leave the coq workers it spawned running.
    """
    try:
        os.killpg(os.getpgid(process.pid), sig)
    except (AttributeError, ProcessLookupError, OSError):
        process.send_signal(sig)


def _free_port(host: str = "127.0.0.1") -> int:
    """Ask the kernel for an unused port."""
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_config():
    """Address the test session should talk to.

    By default the port comes from the ephemeral range, so two test sessions
    running at once never end up sharing a server. Set
    PETANQUE_TEST_ADDR=host:port to point the suite at a pet-server you
    started yourself; the suite will then not start or stop one.
    """
    addr = os.environ.get("PETANQUE_TEST_ADDR")
    if addr:
        host, sep, port = addr.rpartition(":")
        if not sep or not host or not port.isdigit():
            pytest.fail(
                f"PETANQUE_TEST_ADDR must look like host:port, got {addr!r}"
            )
        return {"host": host, "port": int(port), "external": True}
    return {"host": "127.0.0.1", "port": _free_port(), "external": False}


@pytest.fixture(scope="session")
def petanque_server(server_config) -> Generator[subprocess.Popen, None, None]:
    """
    Start and manage the Petanque server process for the test session.

    Starts pet-server on the address from ``server_config``, waits for it to
    accept connections, yields the process, and shuts it down afterwards. If
    PETANQUE_TEST_ADDR named an external server, this yields None and leaves
    that server alone.
    """
    host = server_config["host"]
    port = server_config["port"]

    if server_config["external"]:
        if not is_port_open(host, port):
            pytest.fail(f"No pet-server listening on {host}:{port}")
        logger.info(f"Using the external server on {host}:{port}")
        yield None
        return

    logger.info(f"Starting pet-server on port {port}")
    try:
        process = subprocess.Popen(
            ["pet-server", "-p", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=(
                os.setsid if os.name != "nt" else None
            ),  # Create process group on Unix
        )
    except FileNotFoundError:
        pytest.skip(
            "pet-server executable not found in PATH. Please ensure pet-server is installed and available."
        )

    try:
        # Poll rather than sleeping a fixed amount: a warm machine is ready in
        # well under a second, a loaded one can take much longer than five.
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while not is_port_open(host, port):
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(
                    f"Pet-server exited with code {process.returncode} "
                    f"before accepting connections.\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
            if time.monotonic() > deadline:
                _terminate(process)
                stdout, stderr = process.communicate(timeout=5)
                pytest.fail(
                    f"Pet-server failed to start within {STARTUP_TIMEOUT} seconds."
                    f"\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
            time.sleep(0.05)

        logger.info(f"Pet-server started successfully on port {port}")
        yield process

    finally:
        if process.poll() is None:
            logger.info("Shutting down pet-server")
            _terminate(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Pet-server didn't shut down gracefully, forcing kill")
                _terminate(process, signal.SIGKILL)
                process.wait()
            logger.info("Pet-server shut down")


@pytest.fixture(scope="session")
def example_files():
    """Paths to example files."""
    return {"foo_v": "./examples/foo.v", "examples_dir": "./examples/"}


@pytest.fixture(scope="function")
def client(server_config, petanque_server):
    """Create a Pytanque client for each test."""
    # petanque_server fixture ensures server is running
    return Pytanque(server_config["host"], server_config["port"])


@pytest.fixture(scope="function")
def connected_client(server_config, petanque_server):
    """Create and connect a Pytanque client for each test."""
    # petanque_server fixture ensures server is running
    client = Pytanque(server_config["host"], server_config["port"])
    try:
        client.connect()
        yield client
    finally:
        client.close()
