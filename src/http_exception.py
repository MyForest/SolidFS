class HTTPStatusCodeException(Exception):
    def __init__(self, https_http_status_code: int, message: str | None = None):
        if not isinstance(https_http_status_code, int):
            raise Exception("Expected integer HTTP status code")
        self._https_http_status_code = https_http_status_code
        if message is None:
            message = f"HTTP status code {https_http_status_code}"
        super().__init__()
        if message:
            self.message = message
        else:
            self.message = self.default_message

    @property
    def http_response_code(self) -> int:
        return self._https_http_status_code

    @property
    def default_message(self) -> str:
        return "HTTP exception"


class HTTPStatusCodeWithRangeException(HTTPStatusCodeException):

    def __init__(self, https_http_status_code: int, message: str | None = None):
        if not isinstance(https_http_status_code, int):
            raise Exception("Expected integer HTTP status code")
        self.check_in_range(https_http_status_code)
        super().__init__(https_http_status_code, message)

    def check_in_range(self, https_http_status_code: int):

        if https_http_status_code < self.range[0]:
            raise Exception(f"HTTP status code of {https_http_status_code} is lower than the minimum allowed of {self.range[0]}")

        if https_http_status_code > self.range[1]:
            raise Exception(f"HTTP status code of {https_http_status_code} is higher than the maximum allowed of {self.range[1]}")

    @property
    def range(self) -> tuple[int, int]:
        return 100, 599


class HTTPStatusCodeWithFixedValueException(HTTPStatusCodeWithRangeException):

    def __init__(self, message: str | None = None):
        super().__init__(self.expected_https_http_status_code, message)

    @property
    def expected_https_http_status_code(self) -> int:
        return 0

    @property
    def range(self) -> tuple[int, int]:
        return self.expected_https_http_status_code, self.expected_https_http_status_code


class RedirectionException(HTTPStatusCodeException):
    """3xx"""

    @property
    def range(self) -> tuple[int, int]:
        return 300, 399


class BadRequestException(HTTPStatusCodeException):
    """4xx"""

    @property
    def range(self) -> tuple[int, int]:
        return 400, 499

    @property
    def default_message(self) -> str:
        return "Bad request"


class UnauthorizedException(BadRequestException, HTTPStatusCodeWithFixedValueException):
    """401"""

    @property
    def expected_https_http_status_code(self) -> int:
        return 401


class ForbiddenException(BadRequestException, HTTPStatusCodeWithFixedValueException):
    """403"""

    @property
    def expected_https_http_status_code(self) -> int:
        return 403

    @property
    def default_message(self) -> str:
        return "Forbidden"


class NotFoundException(BadRequestException, HTTPStatusCodeWithFixedValueException):
    """404"""

    @property
    def expected_https_http_status_code(self) -> int:
        return 404


class NotAcceptableException(BadRequestException, HTTPStatusCodeWithFixedValueException):
    """406"""

    @property
    def expected_https_http_status_code(self) -> int:
        return 406


class ServerException(HTTPStatusCodeException):
    """5xx"""

    @property
    def range(self) -> tuple[int, int]:
        return 500, 599


class HTTPStatusCodeToException:
    @staticmethod
    def raise_exception_for_failed_requests(http_status_code: int, response_text: str | None = None) -> None:
        """Allows greater control in response to problems than Response.raise_for_status"""

        if http_status_code < 300:
            return

        if http_status_code >= 300 and http_status_code < 400:
            raise RedirectionException(http_status_code, response_text)

        if http_status_code == 404:
            raise NotFoundException(response_text)

        if http_status_code == 401:
            raise UnauthorizedException(response_text)

        if http_status_code == 403:
            raise ForbiddenException(response_text)

        if http_status_code == 406:
            raise NotAcceptableException(response_text)

        if http_status_code >= 400 and http_status_code < 500:
            raise BadRequestException(http_status_code, response_text)

        if http_status_code >= 500 and http_status_code < 600:
            raise ServerException(http_status_code, response_text)

        if http_status_code >= 600:
            raise Exception(f"Unexpected HTTP status code {http_status_code}: {response_text}")
