#!/usr/bin/env python3
import email.utils
import errno
import stat
import uuid
from stat import S_IFDIR, S_IFREG
from typing import Generator

import fuse
import magic
import structlog
from fuse import Fuse
from rdflib.term import URIRef

from app_logging import AppLogging
from solid_request import SolidRequest
from solid_resource import Container, Resource, ResourceStat, URIRefHelper
from solidfs_resource_hierarchy import SolidResourceHierarchy

fuse.fuse_python_api = (0, 2)


class SolidFS(Fuse):
    def __init__(self, *args, **kw):
        session_identifier = uuid.uuid4().hex
        self._logger = structlog.getLogger(self.__class__.__name__).bind(session_identifier=session_identifier)
        self.requestor = SolidRequest(session_identifier)

        Fuse.__init__(self, *args, **kw)
        self.fd = 0
        self.hierarchy = SolidResourceHierarchy(self.requestor)

    @staticmethod
    def check_path_is_safe(path: str) -> None:
        """Apply simple checks to the path to stop common problems. This does not ensure it will be OK on the Solid server."""
        assert isinstance(path, str)
        assert path.startswith("/")
        assert len(path) < 1024

    def chmod(self, path, mode):
        SolidFS.check_path_is_safe(path)
        self._logger.warning("Changing mode is not supported", path=path, mode=mode)
        return 0

    def chown(self, path, uid, gid):
        SolidFS.check_path_is_safe(path)
        self._logger.warning("Changing owner is not supported", path=path, uid=uid, gid=gid)
        return 0

    def create(self, path: str, mode, umask) -> int:
        """Create a Resource"""

        SolidFS.check_path_is_safe(path)

        self._logger.debug("create", path=path, mode=mode, umask=umask)
        parent, name = path.rsplit("/", 1)
        container = self.hierarchy.get_resource_by_path(parent)
        if not isinstance(container, Container):
            raise Exception(f"Parent {container} is not a Solid Container")

        # Default to an being unknown content type (https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types)
        content_type = "application/octet-stream"

        headers = {"Link": '<http://www.w3.org/ns/ldp#Resource>; rel="type"', "Content-Type": content_type}

        resource_url = container.uri + URIRef(name)
        with structlog.contextvars.bound_contextvars(resource_url=resource_url):

            self._logger.info("Creating Solid Resource", parent=parent, name=name, mode=mode, content_type=content_type)
            try:
                # Use PUT so the name on the server matches the requested path
                response = self.requestor.request("PUT", resource_url.toPython(), headers=headers)

                if response.status_code in [201, 204]:
                    new_resource = Resource(resource_url, ResourceStat(0, S_IFREG | 0o777))

                    if container.contains is None:
                        container.contains = set()
                    container.contains.add(new_resource)
                    return 0

                self._logger.error(f"Error creating Solid Resource on server", status_code=response.status_code, text=response.content, exc_info=True)

            except:
                self._logger.error(f"Creation request failed for Solid Resource", exc_info=True)

        return -errno.ENOENT

    def _refresh_resource_stat(self, resource: Resource) -> None:

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
            self._logger.debug("Access modes", allowed=allowed)
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

    def getattr(self, path: str) -> fuse.Stat:
        SolidFS.check_path_is_safe(path)

        with structlog.contextvars.bound_contextvars(path=path):
            self._logger.debug("getattr")
            try:
                resource = self.hierarchy.get_resource_by_path(path)
                with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
                    self._logger.debug("Reviewing Resource stats")
                    if resource.stat.st_mtime == 0:
                        try:
                            self._refresh_resource_stat(resource)
                        except:
                            self._logger.exception("Refresh Resource stat")

                return resource.stat
            except:
                return -errno.ENOENT

    def mkdir(self, path: str, mode) -> int:
        """Create a Container"""
        # TODO: Understand nlink
        # TODO: Use mode

        SolidFS.check_path_is_safe(path)
        assert not path.endswith("/")

        self._logger.debug("mkdir", path=path, mode=mode)

        with structlog.contextvars.bound_contextvars(path=path):
            parent, name = path.rsplit("/", 1)
            parent_container = self.hierarchy.get_resource_by_path(parent)
            if not isinstance(parent_container, Container):
                raise Exception(f"Parent of {path} is not a Container. It is at {parent_container.uri}")

            with structlog.contextvars.bound_contextvars(parent_container_url=parent_container.uri, name=name):

                target_uri = parent_container.uri + URIRef(name + "/")
                quoted_url = URIRefHelper.to_quoted_url(target_uri)
                self._logger.info("Creating Solid Container", target_uri=target_uri, quoted_url=quoted_url)
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

                    self._logger.error(f"Error creating Solid Container on server", status_code=response.status_code, text=response.text, exc_info=True)

                except:
                    self._logger.error(f"Unable to create Solid Container", exc_info=True)

            return -errno.ENOENT

    def open(self, path: str, flags):
        SolidFS.check_path_is_safe(path)
        self._logger.debug("open", path=path, flags=flags)
        return 0

    def read(self, path: str, size: int, offset: int) -> bytes:

        SolidFS.check_path_is_safe(path)

        with structlog.contextvars.bound_contextvars(path=path):
            self._logger.debug("read", size=size, offset=offset)

            resource = self.hierarchy.get_resource_by_path(path)
            content_to_return = resource.content.get()
            if not content_to_return is None:
                self._logger.debug(f"Retrieved content from cache", size=len(content_to_return))
            else:
                self._logger.debug(f"Fetching {size} bytes from {resource.uri}")

                response = self.requestor.request("GET", resource.uri.toPython(), headers={"Accept": "*"})

                if response.status_code == 200:
                    content_to_return = response.content
                    resource.content.set(content_to_return)
                    resource.stat.st_size = len(content_to_return)
                else:
                    raise Exception(f"Error reading Solid resource {resource.uri} with code {response.status_code}: {response.text}")

            if size:
                trimmed_content = content_to_return[offset : offset + size]
                self._logger.debug("Returning specified number of bytes", size=size, offset=offset, returning_size=len(trimmed_content))
                return trimmed_content

            self._logger.debug("Returning all bytes", size=len(content_to_return))
            return content_to_return

    def readdir(self, path: str, offset) -> Generator[fuse.Direntry, None, None]:
        SolidFS.check_path_is_safe(path)

        with structlog.contextvars.bound_contextvars(path=path):
            self._logger.debug("readdir", offset=int)

            resource = self.hierarchy.get_resource_by_path(path)
            if not isinstance(resource, Container):
                raise Exception(f"{resource.uri} is not a Solid Container so we cannot 'readdir' on it")

            with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
                contained_resources = self.hierarchy.get_contained_resources(resource)
                yield from [fuse.Direntry(r) for r in [".", ".."]]

                for contained_resource in contained_resources:
                    # We need to strip the terminating slash off Containers because fuse crashes if they are included
                    name = str(URIRefHelper.relative_to(resource.uri, contained_resource.uri)).rstrip("/")
                    self._logger.info("Returning directory entry", name=name, uri=resource.uri)
                    dir_entry = fuse.Direntry(name)

                    if isinstance(contained_resource, Resource):
                        dir_entry.type = stat.S_IFREG
                    if isinstance(contained_resource, Container):
                        dir_entry.type = stat.S_IFDIR

                    assert dir_entry.type
                    yield dir_entry

    def rename(self, source: str, target: str) -> int:
        SolidFS.check_path_is_safe(source)
        SolidFS.check_path_is_safe(target)

        self._logger.debug("rename", source=source, target=target)

        source_resource = self.hierarchy.get_resource_by_path(source)
        content = self.read(source, source_resource.stat.st_size, 0)

        self.create(target, source_resource.stat.st_mode, None)
        self.write(target, content, 0)
        self.unlink(source)
        return 0

    def rmdir(self, path: str):
        SolidFS.check_path_is_safe(path)
        self._logger.debug("rmdir", path=path)
        self.unlink(path)

    def truncate(self, path: str, size: int):
        SolidFS.check_path_is_safe(path)
        self._logger.warning("Truncation is not supported", path=path, size=size)
        return 0

    def unlink(self, path: str) -> int:
        """Delete a Resource"""

        SolidFS.check_path_is_safe(path)

        self._logger.debug("unlink", path=path)
        with structlog.contextvars.bound_contextvars(path=path):
            resource = self.hierarchy.get_resource_by_path(path)

            try:
                response = self.requestor.request("DELETE", resource.uri.toPython())

                if response.status_code in [200, 204]:  # We don't support 202 yet
                    parent = self.hierarchy.get_parent(path)
                    if not parent.contains is None:
                        parent.contains.remove(resource)
                    return 0

                self._logger.error(f"Deleting Solid Resource failed", status_code=response.status_code, text=response.text, exc_info=True)

            except:
                self._logger.error(f"Unable to delete Solid Resource", exc_info=True)

            return -errno.ENOENT

    def utime(self, path: str, times: tuple[int, int]):
        SolidFS.check_path_is_safe(path)
        self._logger.warning("Unable to set times on Solid Resource", path=path, times=times)
        return 0

    def write(self, path: str, buf: bytes, offset: int) -> int:
        """Write a Resource"""

        SolidFS.check_path_is_safe(path)
        assert isinstance(buf, bytes)
        self._logger.debug("write", path=path, size=len(buf), offset=offset)

        with structlog.contextvars.bound_contextvars(path=path):
            resource = self.hierarchy.get_resource_by_path(path)
            existing_content = bytes()
            if offset != 0:
                existing_content = resource.content.get()
                if existing_content is None:
                    try:
                        self._logger.info("Reading existing bytes")
                        existing_content = self.read(path, 10000000, 0)
                        self._logger.info("Read existing bytes", size=len(existing_content))
                    except:
                        self._logger.info("Unable to read existing bytes", exc_info=True)
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
                self._logger.warning("Could not determine mime type from bytes")
                pass

            self._logger.info(
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
                if offset < 4096:
                    # If content type varies then some Solid servers won't alter their view of the content so we have to DELETE the old content first
                    # Don't use unlink because it will remove meta data
                    response = self.requestor.request("DELETE", resource.uri.toPython(), headers=headers)
                else:
                    # Content type is based on a few magic bytes at the start so content after that won't alter the content type
                    pass
                response = self.requestor.request("PUT", resource.uri.toPython(), headers=headers, data=revised_content)

                if response.status_code in [201, 204]:
                    self._logger.debug("Wrote bytes to Solid server", size=len(revised_content), status_code=response.status_code)
                    return len(buf)

                self._logger.error("Error writing Solid Resource to server", status_code=response.status_code, exc_info=True)
                return -1
            except:
                self._logger.error("Unable to write Solid Resource", exc_info=True)
                return -1


if __name__ == "__main__":
    AppLogging.configure_logging()

    usage = (
        """
SolidFS enables a file system interface to a Solid Pod
"""
        + Fuse.fusage
    )
    server = SolidFS(version="%prog " + fuse.__version__, usage=usage, dash_s_do="setsingle")

    server.parser.add_option(mountopt="root", metavar="PATH", default="/data/", help="Surface Pod at PATH [default: %default]")
    server.parse(errex=1)
    server.main()
