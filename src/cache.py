import os

import structlog


class Cache:
    def get(self) -> bytes | None:
        pass

    def set(self, content: bytes) -> None:
        pass


class NullCache(Cache):

    def get(self) -> bytes | None:
        return None

    def set(self, _: bytes) -> None:
        pass


class ActiveCache(Cache):

    def __init__(self) -> None:
        self.content: bytes | None = None

    def get(self) -> bytes | None:
        structlog.get_logger().debug("Returning from cache", size=len(self.content or []), exists=(not self.content is None))
        return self.content

    def set(self, content: bytes) -> None:
        self.content = content


class CacheFactory:

    @staticmethod
    def get_cache() -> Cache:
        # if os.environ.get("SOLIDFS_CONTENT_CACHING") == "1":
        #     return ActiveCache()

        return NullCache()
