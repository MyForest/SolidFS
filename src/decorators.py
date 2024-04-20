import functools

import structlog


class Decorators:

    @staticmethod
    def log_not_supported(func):
        """Indicates the method isn't supported, but will return as though it succeeded"""

        @functools.wraps(func)
        def wrapper(*args, **kwarg):
            scalar_args = [arg for arg in args if type(arg) in [int, str, bool]]
            logger = structlog.getLogger(func.__qualname__.split(".")[0])
            logger.warning("Not supported", function_name=func.__name__, scalar_args=scalar_args)
            return 0

        return wrapper

    @staticmethod
    def add_path_to_logging_context(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with structlog.contextvars.bound_contextvars(path=args[1]):
                return func(*args, **kwargs)

        return wrapper

    @staticmethod
    def log_invocation_with_scalar_args(func):
        """Limit the logging to scalar arguments so we don't overwhelm the logger"""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with structlog.contextvars.bound_contextvars(function_name=func.__name__):
                scalar_args = [arg for arg in args if type(arg) in [int, str, bool]]
                logger = structlog.getLogger(func.__qualname__.split(".")[0])
                logger.debug(func.__name__, scalar_args=scalar_args)
                return func(*args, **kwargs)

        return wrapper
