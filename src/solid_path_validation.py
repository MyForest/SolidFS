#!/usr/bin/env python3
import errno
import functools
import logging
import os

import structlog

from http_exception import HTTPStatusCodeException
from http_to_errno import HTTPToErrNo


class SolidPathValidation:
    def __init__(self):
        self._logger = structlog.getLogger(self.__class__.__name__)

    @staticmethod
    def customize_return_based_on_exception_type(func):
        """
        Known-exception types are gracelly mapped to expected return codes.
        Unknown exceptions are logged with exception info and a generic return code is returned.
        """

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = structlog.getLogger(SolidPathValidation.__name__)
            try:
                return func(*args, **kwargs)
            except HTTPStatusCodeException as http_exception:
                error_number = HTTPToErrNo.http_to_errno(http_exception.http_response_code)
                return -error_number
            except:
                logger.exception("Unknown exception", exc_info=True)
                return -errno.EBADMSG

        return wrapper

    @staticmethod
    def validate_path(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            validation_code = SolidPathValidation.get_path_validation_result_code(args[1])
            if validation_code:
                return -validation_code
            return func(*args, **kwargs)

        return wrapper

    @staticmethod
    def _log_exception_and_return_code(code: int) -> int:
        """Makes currying easier"""
        logging.exception(os.strerror(code))
        return code

    @staticmethod
    def get_path_validation_result_code(path: str) -> int:
        """Return a code indicating if there is a problem with the path. Result is from 'errno'. This does not ensure it will be OK on the Solid server."""
        if not isinstance(path, str):
            return SolidPathValidation._log_exception_and_return_code(errno.EFAULT)

        # A very specific name so we can test error handling
        if "6291403e-8887-40ec-9e6d-7f394008a979" in path:
            return SolidPathValidation._log_exception_and_return_code(errno.EINVAL)

        if not path.startswith("/"):
            return SolidPathValidation._log_exception_and_return_code(errno.ENOTDIR)

        if len(path) > 1024:
            return SolidPathValidation._log_exception_and_return_code(errno.ENAMETOOLONG)

        return 0

    @staticmethod
    def check_path_is_valid(path: str) -> None:
        """Raise an exception if the path is not valid. See 'get_path_validation_result_code' for more details."""
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            raise Exception(os.strerror(validation_code))
