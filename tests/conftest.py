# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""Shared pytest setup.

The suite must run offline, so every test runs with outbound network
connections blocked: a test that tries to download something fails
instead of silently depending on the network.
"""

import socket

import pytest


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise NetworkBlocked('tests must not use the network')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket.socket, 'connect_ex', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)


@pytest.fixture
def pdf_path(tmp_path):
    """Write PDF bytes to a temporary file and return its path."""
    def write(data, name='test.pdf'):
        path = tmp_path / name
        path.write_bytes(data)
        return path
    return write
