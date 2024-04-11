#!/usr/bin/env python3
import email.utils
import errno
import os
import stat
import uuid
from stat import S_IFDIR, S_IFREG
from time import time
from typing import Generator, Iterable

import fuse
import magic
import structlog
from fuse import Fuse
from rdflib import Graph
from rdflib.term import URIRef

from app_logging import AppLogging
from solid_request import SolidRequest
from solid_resource import Container, Resource, ResourceStat, URIRefHelper

fuse.fuse_python_api = (0, 2)


class Solid(Fuse):
    def __init__(self, *args, **kw):
        session_identifier = uuid.uuid4().hex
        self.__logger = structlog.getLogger(self.__class__.__name__).bind(session_identifier=session_identifier)
        self.requestor = SolidRequest(session_identifier)

        Fuse.__init__(self, *args, **kw)
        self.fd = 0
        self.root: Container | None = None

        self.now = time()

    def get_root(self) -> Container:
        if self.root is None:
            base_url = os.environ.get("SOLIDFS_BASE_URL")
            if base_url is None:
                self.__logger.exception("Please set the 'SOLIDFS_BASE_URL'")
                raise Exception("Please set the 'SOLIDFS_BASE_URL'")
            self.__logger.info("Establishing root", base_url=base_url)
            self.root = Container(URIRef(base_url) + "/", ResourceStat(mode=S_IFDIR | 0o777, nlink=2))

        return self.root

    def check_path_is_safe(self, path: str) -> None:
        assert isinstance(path, str)
        assert path.startswith("/")
        assert len(path) < 1024

    def get_resource_by_path(self, relative_path: str, start: Resource | None = None) -> Resource:
        """Map a file-system path, delimited by /, to a Resource's URI"""

        if relative_path in ["/", ""]:
            return self.get_root()

        if start is None:
            start = self.get_root()

        if relative_path == ".":
            return start

        parts = relative_path.lstrip("/").split("/")
        current = start
        for part in parts:
            if not isinstance(current, Container):
                raise Exception(f"{current.uri} is not a Container")

            # Hack because the path does not come with a slash from the OS
            expected_urls = [current.uri + part, current.uri + part + "/"]
            found = False
            for contained in self.get_contained_resources(current):
                if contained.uri in expected_urls:
                    current = contained
                    found = True
                    break
            if not found:
                raise Exception(f"{part} not found in {current.uri} when looking for {relative_path} from {start.uri}")

        return current

    def get_contained_resources(self, container: Container) -> Iterable[Resource]:

        with structlog.contextvars.bound_contextvars(resource_url=container.uri):
            if container.contains is None:
                quoted_url = URIRefHelper.to_quoted_url(container.uri)
                self.__logger.debug("Determining contents of Container", quoted_url=quoted_url)

                response = self.requestor.request("GET", quoted_url, headers={"Accept": "text/turtle,application/rdf+xml,application/ld+json"})

                if response.status_code == 200:
                    content = response.content
                    self.__logger.debug("Parsing Container RDF", size=len(content))
                    g = Graph()
                    g.parse(data=content, publicID=container.uri)
                    # The URIs in the graph are quoted, but our in-memory URIs are UTF-8 encoded strings in URIRefs which aren't quoted
                    ldp_contained = list(g.objects(URIRef(URIRefHelper.to_quoted_url(container.uri)), URIRef("http://www.w3.org/ns/ldp#contains")))

                    items = set[Resource]()
                    self.__logger.debug("Contains", size=len(ldp_contained))
                    for quoted_resource in ldp_contained:
                        if not isinstance(quoted_resource, URIRef):
                            raise Exception(f"Expected {quoted_resource} to be a URIRef but it was {type(quoted_resource)}")
                        resource = URIRefHelper.from_quoted_url(quoted_resource.toPython())
                        self.__logger.debug("Discovered contained Resource", uri=resource)
                        if str(resource).endswith("/"):
                            items.add(Container(resource, ResourceStat(mode=stat.S_IFDIR | 0o755, nlink=2)))
                        else:
                            items.add(Resource(resource, ResourceStat(size=1000000, mode=stat.S_IFREG | 0o444)))

                    container.contains = items
                else:
                    raise Exception(f"Error fetching Solid resource {container.uri} with code {response.status_code}: {response.text}")

            return container.contains

    def chmod(self, path, mode):
        self.__logger.warning("Changing mode is not supported", path=path)
        return 0

    def chown(self, path, uid, gid):
        self.__logger.warning("Changing owner is not supported", path=path)
        return 0

    def create(self, path: str, mode, umask) -> int:
        """Create a Resource"""

        self.check_path_is_safe(path)

        parent, name = path.rsplit("/", 1)
        container = self.get_resource_by_path(parent)
        if not isinstance(container, Container):
            raise Exception(f"Parent {container} is not a Solid Container")

        # Default to an being unknown (https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types)
        content_type = "application/octet-stream"

        headers = {"Link": '<http://www.w3.org/ns/ldp#Resource>; rel="type"', "Content-Type": content_type}

        resource_url = container.uri + URIRef(name)
        with structlog.contextvars.bound_contextvars(resource_url=resource_url):

            self.__logger.info("Creating Solid Resource", parent=parent, name=name, mode=mode, content_type=content_type)
            try:
                # Use PUT so the name on the server matches the requested path
                response = self.requestor.request("PUT", resource_url.toPython(), headers=headers)

                if response.status_code in [201, 204]:
                    new_resource = Resource(resource_url, ResourceStat(0, S_IFREG | 0o777))

                    if container.contains is None:
                        container.contains = set()
                    container.contains.add(new_resource)
                    return 0

                self.__logger.error(f"Error creating Solid Resource on server", status_code=response.status_code, text=response.content, exc_info=True)

            except:
                self.__logger.error(f"Creation request failed for Solid Resource", exc_info=True)

        return -errno.ENOENT

    def get_parent(self, path: str) -> Container:
        parts = path.split("/")
        container = self.get_resource_by_path("/".join(parts[:-1]))
        if not isinstance(container, Container):
            raise Exception(f"Parent of {path} is not a Container. It is at {container.uri}")
        return container

    def getattr(self, path: str) -> fuse.Stat:
        self.check_path_is_safe(path)

        with structlog.contextvars.bound_contextvars(path=path):
            self.__logger.info("Getting attributes")
            try:
                resource = self.get_resource_by_path(path)
                with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
                    self.__logger.info("Reviewing Resource stats")
                    if resource.stat.st_mtime == 0:
                        try:
                            self.refresh_resource_stat(resource)
                        except:
                            self.__logger.exception("Refresh Resource stat")

                return resource.stat
            except:
                return -errno.ENOENT

    def refresh_resource_stat(self, resource: Resource) -> None:

        response = self.requestor.request(
            "HEAD",
            resource.uri.toPython(),
            headers={"Accept": "*"},
        )

        if "Last-Modified" in response.headers:
            last_modified = email.utils.parsedate_to_datetime(response.headers["Last-Modified"])
            resource.stat.st_mtime = int(last_modified.timestamp())

        if "WAC-Allow" in response.headers:
            allowed = response.headers["WAC-Allow"].strip()
            # user="read control write"
            # TODO: Wrong parsing
            self.__logger.debug("Access modes", allowed=allowed)
            access_modes = allowed.split("=")[-1].replace('"', "").split(" ")
            resource_mode = stat.S_IRWXU  # Don't open up any further | stat.S_IRWXG | stat.S_IRWXO
            if isinstance(resource, Container):
                resource_mode |= stat.S_IFDIR
            else:
                resource_mode |= stat.S_IFREG

            if "read" in access_modes:
                resource_mode |= stat.S_IRUSR
            if "write" in access_modes:
                resource_mode |= stat.S_IWUSR
            if "append" in access_modes:
                pass
            if "control" in access_modes:
                pass
            resource.stat.st_mode = resource_mode

    def mkdir(self, path: str, mode) -> int:
        """Create a Container"""
        # TODO: Understand nlink
        # TODO: Use mode

        self.check_path_is_safe(path)
        assert not path.endswith("/")

        with structlog.contextvars.bound_contextvars(path=path):
            # resource = self.get_resource_by_path(path)
            parent, name = path.rsplit("/", 1)
            parent_container = self.get_resource_by_path(parent)
            if not isinstance(parent_container, Container):
                raise Exception(f"Parent of {path} is not a Container. It is at {parent_container.uri}")

            with structlog.contextvars.bound_contextvars(parent_container_url=parent_container.uri, name=name):

                target_uri = parent_container.uri + URIRef(name + "/")
                quoted_url = URIRefHelper.to_quoted_url(target_uri)
                self.__logger.info("Creating Solid Container", target_uri=target_uri, quoted_url=quoted_url)
                headers = {
                    "Link": '<http://www.w3.org/ns/ldp#BasicContainer>; rel="type"',
                    "Content-Type": "text/turtle",
                }

                try:
                    response = self.requestor.request("PUT", quoted_url, headers=headers)
                    if response.status_code in [201, 204]:
                        new_container = Container(target_uri, ResourceStat(mode=S_IFDIR | 0o777, nlink=2))
                        if parent_container.contains is None:
                            parent_container.contains = set()
                        parent_container.contains.add(new_container)

                        return 0

                    self.__logger.error(f"Error creating Solid Container on server", status_code=response.status_code, text=response.text, exc_info=True)

                except:
                    self.__logger.error(f"Unable to create Solid Container", exc_info=True)

            return -errno.ENOENT

    def open(self, path: str, flags):
        self.check_path_is_safe(path)
        return 0

    def read(self, path: str, size: int, offset: int) -> bytes:

        self.check_path_is_safe(path)

        with structlog.contextvars.bound_contextvars(path=path):
            resource = self.get_resource_by_path(path)
            content_to_return = resource.content.get()
            if not content_to_return is None:
                self.__logger.debug(f"Retrieved content from cache", size=len(content_to_return))
            else:
                self.__logger.debug(f"Fetching {size} bytes from {resource.uri}")

                response = self.requestor.request("GET", resource.uri.toPython(), headers={"Accept": "*"})

                if response.status_code == 200:
                    content_to_return = response.content
                    resource.content.set(content_to_return)
                    resource.stat.st_size = len(content_to_return)
                else:
                    raise Exception(f"Error reading Solid resource {resource.uri} with code {response.status_code}: {response.text}")

            if size:
                trimmed_content = content_to_return[offset : offset + size]
                self.__logger.debug("Returning specified number of bytes", size=size, offset=offset, returning_size=len(trimmed_content))
                return trimmed_content

            self.__logger.debug("Returning all bytes", size=len(content_to_return))
            return content_to_return

    def readdir(self, path: str, offset) -> Generator[fuse.Direntry, None, None]:
        self.check_path_is_safe(path)

        with structlog.contextvars.bound_contextvars(path=path):

            self.__logger.debug(f"Reading dir")

            resource = self.get_resource_by_path(path)
            if not isinstance(resource, Container):
                raise Exception(f"{resource.uri} is not a Solid Container so we cannot 'readdir' on it")

            with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
                contained_resources = self.get_contained_resources(resource)
                yield from [fuse.Direntry(r) for r in [".", ".."]]

                for contained_resource in contained_resources:
                    # We need to strip the terminating slash off Containers because fuse crashes if they are included
                    name = str(URIRefHelper.relative_to(resource.uri, contained_resource.uri)).rstrip("/")
                    self.__logger.info("Returning directory entry", name=name, uri=resource.uri)
                    dir_entry = fuse.Direntry(name)

                    if isinstance(contained_resource, Resource):
                        dir_entry.type = stat.S_IFREG
                    if isinstance(contained_resource, Container):
                        dir_entry.type = stat.S_IFDIR

                    assert dir_entry.type
                    yield dir_entry

    def rename(self, source, target) -> int:
        self.check_path_is_safe(source)
        self.check_path_is_safe(target)

        source_resource = self.get_resource_by_path(source)
        content = self.read(source, source_resource.stat.st_size, 0)

        self.create(target, source_resource.stat.st_mode, None)
        self.write(target, content, 0)
        self.unlink(source)
        return 0

    def rmdir(self, path: str):
        self.unlink(path)

    def truncate(self, path: str, size):
        self.check_path_is_safe(path)
        self.__logger.warning("Truncation is not supported", path=path)
        return 0

    def unlink(self, path: str) -> int:
        """Delete a Resource"""

        self.check_path_is_safe(path)

        with structlog.contextvars.bound_contextvars(path=path):
            resource = self.get_resource_by_path(path)

            try:
                response = self.requestor.request("DELETE", resource.uri.toPython())

                if response.status_code in [200, 204]:  # We don't support 202 yet
                    parent = self.get_parent(path)
                    if not parent.contains is None:
                        parent.contains.remove(resource)
                    return 0

                self.__logger.error(f"Deleting Solid Resource failed", status_code=response.status_code, text=response.text, exc_info=True)

            except:
                self.__logger.error(f"Unable to delete Solid Resource", exc_info=True)

            return -errno.ENOENT

    def utime(self, path: str, times: tuple[int, int]):
        self.check_path_is_safe(path)
        self.__logger.warning("Unable to set times on Solid Resource", path=path, times=times)
        return 0

    def write(self, path: str, buf: bytes, offset: int) -> int:
        """Write a Resource"""

        self.check_path_is_safe(path)
        assert isinstance(buf, bytes)

        with structlog.contextvars.bound_contextvars(path=path):
            resource = self.get_resource_by_path(path)
            existing_content = bytes()
            if offset != 0:
                existing_content = resource.content.get()
                if existing_content is None:
                    try:
                        self.__logger.info("Reading existing bytes")
                        existing_content = self.read(path, 10000000, 0)
                        self.__logger.info("Read existing bytes", size=len(existing_content))
                    except:
                        self.__logger.info("Unable to read existing bytes", exc_info=True)
                        existing_content = bytes()
                        pass
                    resource.content.set(existing_content)

            extra_content_length = len(buf)
            assert extra_content_length < 10**6
            previous_length = len(existing_content)
            revised_content = existing_content[:offset] + buf + existing_content[offset + len(buf) :]
            resource.content.set(revised_content)
            resource.stat.st_size = len(revised_content)

            content_type = "application/octet-stream"
            try:
                magic_mime = magic.from_buffer(revised_content, mime=True)
                if magic_mime:
                    content_type = magic_mime
            except:
                self.__logger.warning("Could not determine mime type from bytes")
                pass

            self.__logger.info(
                "Content",
                content_type=content_type,
                magic_mime=magic_mime,
                offset=offset,
                extra_content_length=extra_content_length,
                previous_length=previous_length,
                new_content_length=resource.stat.st_size,
            )
            headers = {"Content-Type": content_type, "Content-Length": str(len(revised_content))}

            try:
                # If content type varies then Solid server won't alter it's view of the content so we have to DELETE the old content first
                # Don't use unlink because it will remove meta data
                response = self.requestor.request("DELETE", resource.uri.toPython(), headers=headers)
                response = self.requestor.request("PUT", resource.uri.toPython(), headers=headers, data=revised_content)

                if response.status_code in [201, 204]:
                    self.__logger.debug("Wrote bytes to Solid server", size=len(revised_content), status_code=response.status_code)
                    return len(buf)

                self.__logger.error("Error writing Solid Resource to server", status_code=response.status_code, exc_info=True)
                return -1
            except:
                self.__logger.error("Unable to write Solid Resource", exc_info=True)
                return -1


if __name__ == "__main__":
    AppLogging.configure_logging()

    usage = (
        """
SolidFS enables a file system interface to a Solid Pod
"""
        + Fuse.fusage
    )
    server = Solid(version="%prog " + fuse.__version__, usage=usage, dash_s_do="setsingle")

    server.parser.add_option(mountopt="root", metavar="PATH", default="/data/", help="Surface Pod at PATH [default: %default]")
    server.parse(errex=1)
    server.main()
