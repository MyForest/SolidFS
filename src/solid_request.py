import requests
import structlog
from opentelemetry import trace

from solid_authentication import SolidAuthentication


class SolidRequest:
    def __init__(self, session_identifier: str):
        self.__logger = structlog.getLogger(self.__class__.__name__).bind(session_identifier=session_identifier)
        self.__common_headers = {"Session-Identifier": session_identifier, "User-Agent": "SolidFS/v0.0.1"}
        self.__authentication = SolidAuthentication()

    def _get_auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.__authentication.authenticate_with_client_credentials()}",
        }

    @staticmethod
    def _get_trace_headers() -> dict[str, str]:

        # The X prefix is deprecated: https://datatracker.ietf.org/doc/html/rfc6648
        trace_headers = {}

        current_span = trace.get_current_span().get_span_context()

        span_id = current_span.span_id
        if span_id:
            trace_headers["X-Request-ID"] = trace.format_span_id(span_id)
            trace_headers["Request-ID"] = trace.format_span_id(span_id)

        trace_id = current_span.trace_id
        if trace_id:
            trace_headers["X-Correlation-ID"] = trace.format_trace_id(trace_id)
            trace_headers["Correlation-ID"] = trace.format_trace_id(trace_id)

        return trace_headers

    def request(self, method: str, url: str, extra_headers: dict[str, str] = {}, data: bytes | None = None) -> requests.Response:

        headers = self.__common_headers | self._get_auth_headers() | SolidRequest._get_trace_headers() | extra_headers

        with structlog.contextvars.bound_contextvars(method=method, url=url, headers_supplied=sorted(headers.keys())):

            self.__logger.debug("Sending request")

            response = requests.request(
                method,
                url,
                headers=headers,
                data=data,
            )

            self.__logger.debug("Response", headers_returned=sorted(response.headers.keys()), status_code=response.status_code)

        return response
