# A part of pdfrw (https://github.com/pmaupin/pdfrw)
# Copyright (C) 2006-2015 Patrick Maupin, Austin, Texas
# MIT license -- See LICENSE.txt for details

'''
PDF Exceptions and error handling
'''

import logging


# A library must leave output to the application: pdfrw only adds a
# NullHandler, and its warnings appear wherever the application's
# logging configuration sends them.
log = logging.getLogger('pdfrw')
log.addHandler(logging.NullHandler())

# Kept for compatibility: before pdfrw-ng 0.5.0 this handler was attached
# to `log` on import.  It no longer is; call log.addHandler(handler) to
# get the old stderr output back.
fmt = logging.Formatter('[%(levelname)s] %(filename)s:%(lineno)d %(message)s')

handler = logging.StreamHandler()
handler.setFormatter(fmt)


class PdfError(Exception):
    "Abstract base class of exceptions thrown by this module"

    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg


class PdfParseError(PdfError):
    "Error thrown by parser/tokenizer"


class PdfDecryptionError(PdfParseError):
    """An encrypted file cannot be decrypted: the password is wrong or
    missing, the encryption method is not supported, or AES needs
    pycryptodome, which is not installed."""


class PdfOutputError(PdfError):
    "Error thrown by PDF writer"


class PdfOutputEncodingError(PdfOutputError, UnicodeEncodeError):
    """The writer met a str with a character it cannot write: pdfrw
    writes str data, streams included, as latin-1 (#160).

    The message names the object.  It is also a UnicodeEncodeError, with
    the `encoding`, `object`, `start`, `end` and `reason` of the original
    error, so code that caught that before still catches it.
    """

    def __init__(self, msg, error):
        UnicodeEncodeError.__init__(self, error.encoding, error.object,
                                    error.start, error.end, error.reason)
        self.msg = msg

    def __str__(self):
        return self.msg

    def __reduce__(self):
        error = UnicodeEncodeError(self.encoding, self.object, self.start,
                                   self.end, self.reason)
        return type(self), (self.msg, error)


class PdfNotImplementedError(PdfError):
    "Error thrown on missing features"
