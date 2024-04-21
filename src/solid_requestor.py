# Global state
from parallel.loop_on_thread import LoopOnThread

requestor_daemon = LoopOnThread()
"""A separate event loop for efficiently handling websockets"""


class SolidResponse:
    @property
    def status_code(self) -> int:
        pass

    @property
    def links(self) -> dict[str, dict[str, str]]:
        pass

    @property
    def headers(self) -> dict:
        pass

    def json(self) -> dict:
        pass

    @property
    def content(self) -> bytes:
        pass

    @property
    def text(self) -> str:
        pass


class SolidRequestor:

    def request(self, method: str, url: str, extra_headers: dict[str, str] = {}, data: bytes | None = None) -> SolidResponse:
        pass
