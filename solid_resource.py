import urllib.parse
from dataclasses import dataclass, field

import fuse
from rdflib.term import URIRef

from cache import Cache, CacheFactory


class URIRefHelper:
    @staticmethod
    def relative_to(start: URIRef, end: URIRef) -> URIRef:
        return URIRef(str(end)[len(str(start)) :])

    @staticmethod
    def from_quoted_url(quoted_url: str) -> URIRef:
        """Only un-quotes the path"""
        split = list(urllib.parse.urlsplit(quoted_url))
        split[2] = urllib.parse.unquote(split[2])
        return URIRef(urllib.parse.urlunsplit(split))

    @staticmethod
    def to_quoted_url(uri_ref: URIRef) -> str:
        """Only quotes the path"""
        split = list(urllib.parse.urlsplit(uri_ref.toPython()))
        split[2] = urllib.parse.quote(split[2])
        return urllib.parse.urlunsplit(split)


class ResourceStat(fuse.Stat):
    def __init__(self, size: int = 0, mode: int = 0, nlink: int = 1):
        self.st_mode = mode
        self.st_ino = 0
        self.st_dev = 0
        self.st_nlink = nlink
        self.st_uid = 0
        self.st_gid = 0
        self.st_size = size
        self.st_atime = 0
        self.st_mtime = 0
        self.st_ctime = 0


@dataclass
class Resource:
    uri: URIRef
    stat: ResourceStat
    content: Cache = field(default_factory=CacheFactory.get_cache)

    def __hash__(self) -> int:
        return self.uri.__hash__()


@dataclass
class Container(Resource):
    contains: set[Resource] | None = None

    def __hash__(self) -> int:
        return self.uri.__hash__()
