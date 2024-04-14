import requests
import structlog

from solid_authentication import SolidAuthentication
from tracing import Tracing


class RedirectionException(Exception):
    """3xx"""

    pass


class BadRequestException(Exception):
    """4xx"""

    pass


class ResourceNotFoundException(BadRequestException):
    pass


class NoAccessException(BadRequestException):
    pass


class NotAcceptableException(BadRequestException):
    pass


class ServerException(Exception):
    """5xx"""

    pass


class SolidRequest:
    def __init__(self, session_identifier: str):
        self.__logger = structlog.getLogger(self.__class__.__name__).bind(session_identifier=session_identifier)
        self.__common_headers = {"Session-Identifier": session_identifier, "User-Agent": "SolidFS/v0.0.1"}
        self.__authentication = SolidAuthentication(session_identifier)

    def _get_auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.__authentication.authenticate_with_client_credentials()}",
        }

    def request(self, method: str, url: str, extra_headers: dict[str, str] = {}, data: bytes | None = None) -> requests.Response:

        headers = self.__common_headers | self._get_auth_headers() | Tracing.get_trace_headers() | extra_headers

        with structlog.contextvars.bound_contextvars(method=method, url=url, headers_supplied=sorted(headers.keys())):

            self.__logger.debug("Sending request")

            response = requests.request(
                method,
                url,
                headers=headers,
                data=data,
            )

            self.__logger.debug("Response", headers_returned=sorted(response.headers.keys()), status_code=response.status_code)

        self.raise_exception_for_failed_requests(response)

        return response

    def raise_exception_for_failed_requests(self, response: requests.Response) -> None:

        if response.status_code < 300:
            return

        if response.status_code >= 300 and response.status_code < 400:
            raise RedirectionException()

        if response.status_code == 404:
            raise ResourceNotFoundException()

        if response.status_code in [401, 403]:
            raise NoAccessException()

        if response.status_code == 406:
            raise NotAcceptableException()

        if response.status_code >= 400:
            raise ServerException(f"Unable to refresh resource statistics with response code {response.status_code}")
