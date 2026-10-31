# A part of pdfrw-ng, a maintained fork of pdfrw
# MIT license -- See LICENSE.txt for details

"""The pdfrw logger leaves output to the application (#230)."""

import logging
import os
import subprocess
import sys

import pdfrw  # noqa: F401  (configures the 'pdfrw' logger)
from pdfrw.errors import log


def test_only_a_null_handler():
    assert log is logging.getLogger('pdfrw')
    assert log.handlers
    assert all(type(h) is logging.NullHandler for h in log.handlers)


def test_old_names_kept_but_not_attached():
    import pdfrw.errors as errors
    assert isinstance(errors.fmt, logging.Formatter)
    assert type(errors.handler) is logging.StreamHandler
    assert errors.handler.formatter is errors.fmt
    assert errors.handler not in log.handlers


def test_old_handler_restores_output():
    import pdfrw.errors as errors
    record = log.makeRecord('pdfrw', logging.WARNING, 'x.py', 7,
                            'odd thing', None, None)
    assert errors.handler.format(record) == '[WARNING] x.py:7 odd thing'


def test_level_is_left_to_the_application():
    assert log.level == logging.NOTSET


def test_warnings_reach_the_application(caplog):
    with caplog.at_level(logging.WARNING, logger='pdfrw'):
        log.warning('something odd')
    assert [r.getMessage() for r in caplog.records
            if r.name == 'pdfrw'] == ['something odd']


def test_import_prints_nothing_unconfigured():
    # Before #230, pdfrw's own StreamHandler wrote warnings to stderr
    # whatever the application's logging configuration.
    code = ("import pdfrw.errors, logging; "
            "logging.getLogger('pdfrw').warning('should not appear')")
    result = subprocess.run([sys.executable, '-c', code],
                            capture_output=True, text=True, timeout=60,
                            cwd=os.path.dirname(os.path.dirname(
                                os.path.abspath(__file__))))
    assert result.returncode == 0, result.stderr
    assert 'should not appear' not in result.stderr


def test_adding_old_handler_prints_to_stderr():
    code = ("import pdfrw.errors as e; e.log.addHandler(e.handler); "
            "e.log.warning('now visible')")
    result = subprocess.run([sys.executable, '-c', code],
                            capture_output=True, text=True, timeout=60,
                            cwd=os.path.dirname(os.path.dirname(
                                os.path.abspath(__file__))))
    assert result.returncode == 0, result.stderr
    assert result.stderr == '[WARNING] <string>:1 now visible\n'
