#!/usr/bin/env python3
import email.utils
import errno
import stat
import sys
import uuid
from stat import S_IFDIR, S_IFREG
from typing import Generator

import fuse
import structlog
from fuse import Fuse
from opentelemetry.sdk.trace import TracerProvider
from rdflib.term import URIRef

from app_logging import AppLogging
from solid_mime import SolidMime
from solid_path_validation import SolidPathValidation
from solid_request import SolidRequest
from solid_resource import Container, Resource, ResourceStat, URIRefHelper
from solidfs_resource_hierarchy import PathNotFoundException, SolidResourceHierarchy
from tracing import traced

fuse.fuse_python_api = (0, 2)

from opentelemetry import trace


class SolidFS(Fuse):

    def __init__(self, *args, **kw):
        session_identifier = uuid.uuid4().hex
        trace.set_tracer_provider(TracerProvider())
        self._logger = structlog.getLogger(self.__class__.__name__).bind(session_identifier=session_identifier)
        self.requestor = SolidRequest(session_identifier)

        Fuse.__init__(self, *args, **kw)
        self.fd = 0
        self.hierarchy = SolidResourceHierarchy(self.requestor)

    @traced
    def chmod(self, path: str, mode: int) -> int:
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        self._logger.warning("Changing mode is not supported", path=path, mode=mode)
        return 0

    @traced
    def chown(self, path, uid, gid) -> int:
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        self._logger.warning("Changing owner is not supported", path=path, uid=uid, gid=gid)
        return 0

    @traced
    def create(self, path: str, mode, umask) -> int:
        """Create a Resource"""
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        self._logger.debug("create", path=path, mode=mode, umask=umask)
        parent, name = path.rsplit("/", 1)
        container = self.hierarchy.get_resource_by_path(parent)
        if not isinstance(container, Container):
            raise Exception(f"Parent {container} is not a Solid Container")

        # Default to an being unknown content type (https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types)
        resource_url = container.uri + URIRef(name)
        new_resource = Resource(resource_url, ResourceStat(0, S_IFREG | 0o777))
        # The URI doesn't change after creation so we can make an attempt to guess the content type on creation
        SolidMime.update_mime_type_from_uri(new_resource)
        content_type = new_resource.content_type

        headers = {"Link": '<http://www.w3.org/ns/ldp#Resource>; rel="type"', "Content-Type": content_type}

        with structlog.contextvars.bound_contextvars(resource_url=resource_url):

            self._logger.info("Creating Solid Resource", parent=parent, name=name, mode=mode, content_type=content_type)
            try:
                # Use PUT so the name on the server matches the requested path
                response = self.requestor.request("PUT", resource_url.toPython(), headers)

                if response.status_code in [201, 204]:

                    if container.contains is None:
                        container.contains = set()
                    container.contains.add(new_resource)
                    return 0

                self._logger.error(f"Error creating Solid Resource on server", status_code=response.status_code, text=response.content, exc_info=True)

            except:
                self._logger.error(f"Creation request failed for Solid Resource", exc_info=True)

        self._logger.exception("No such path", path=path)
        return -errno.ENOENT

    def _refresh_resource_stat(self, resource: Resource) -> None:

        response = self.requestor.request(
            "HEAD",
            resource.uri.toPython(),
            {"Accept": "*"},
        )

        # Typical Headers
        # "Accept-Patch",
        # "Accept-Post",
        # "Accept-Put",
        # "Allow",
        # "Cache-Control",
        # "Connection",
        # "Content-Type",
        # "Date",
        # "ETag",
        # "Last-Modified",
        # "Link",
        # "Strict-Transport-Security",
        # "Vary",
        # "WAC-Allow"

        if "Content-Type" in response.headers:
            resource.content_type = response.headers["Content-Type"]

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

    @traced
    def getattr(self, path: str) -> fuse.Stat | int:
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        with structlog.contextvars.bound_contextvars(path=path):
            self._logger.debug(sys._getframe().f_code.co_name)
            try:
                resource = self.hierarchy.get_resource_by_path(path)
                with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
                    if resource.stat.st_mtime == 0:
                        self._logger.debug("Refreshing Resource stats")
                        try:
                            self._refresh_resource_stat(resource)
                        except:
                            self._logger.exception("Refresh Resource stat", exc_info=True)

                return resource.stat
            except PathNotFoundException:
                self._logger.debug("No such path")
                return -errno.ENOENT
            except:
                self._logger.exception("Unknown exception", exc_info=True)
                return -errno.EBADMSG

    @traced
    def getxattr(self, path: str, name: str, size: int) -> str | int:
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        self._logger.debug("getxattr", path=path, name=name, size=size)
        if name == "user.mime_type":
            resource = self.hierarchy.get_resource_by_path(path)
            attribute_value = resource.content_type
            if size == 0:
                # We are asked for size of the value.
                return len(attribute_value)
            return attribute_value

        return 0

    @traced
    def listxattr(self, path: str, size: int) -> list | int:
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        self._logger.debug("listxattr", path=path, size=size)
        attribute_list = ["user.mime_type"]
        if size == 0:
            # We are asked for size of the attr list, i.e. joint size of attrs
            # plus null separators.
            return len("".join(attribute_list)) + len(attribute_list)
        return attribute_list

    @traced
    def mkdir(self, path: str, mode) -> int:
        """Create a Container"""
        # TODO: Understand nlink
        # TODO: Use mode

        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        if path.endswith("/"):
            # Peculiarly, the path does not typically arrive with a slash at the end and we make assumptions based on that so let's enforce it
            self._logger.warn("Unexpected slash at end of path", path=path)
            return errno.ENOTDIR

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
                    response = self.requestor.request("PUT", quoted_url, headers)
                    if response.status_code in [201, 204]:
                        new_container = Container(target_uri, ResourceStat(mode=S_IFDIR | 0o777, nlink=2), content_type="text/turtle")
                        if parent_container.contains is None:
                            parent_container.contains = set()
                        parent_container.contains.add(new_container)

                        return 0

                    self._logger.error(f"Error creating Solid Container on server", status_code=response.status_code, text=response.text, exc_info=True)

                except:
                    self._logger.error(f"Unable to create Solid Container", exc_info=True)

            return -errno.ENOENT

    @traced
    def open(self, path: str, flags) -> int:
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        self._logger.debug("open", path=path, flags=flags)
        return 0

    @traced
    def read(self, path: str, size: int, offset: int) -> bytes | int:

        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        with structlog.contextvars.bound_contextvars(path=path):
            self._logger.debug("read", size=size, offset=offset)

            resource = self.hierarchy.get_resource_by_path(path)
            content_to_return = resource.content.get()
            if not content_to_return is None:
                self._logger.debug(f"Retrieved content from cache", size=len(content_to_return))
            else:
                self._logger.debug(f"Fetching", size=size, uri=resource.uri)

                # Note that we're not using a ranged request because fuse asks for very small chunks and the overhead of fetching them is large
                # Specifically, the largest read size as at 2024-04-13 is 131072 bytes.
                response = self.requestor.request("GET", resource.uri.toPython(), {"Accept": "*"})

                if response.status_code == 200:
                    content_to_return = response.content
                    resource.content.set(content_to_return)
                    resource.content_type = response.headers["Content-Type"]
                    resource.stat.st_size = len(content_to_return)
                else:
                    raise Exception(f"Error reading Solid resource {resource.uri} with code {response.status_code}: {response.text}")

            if size:
                trimmed_content = content_to_return[offset : offset + size]
                self._logger.debug("Returning specified number of bytes", size=size, offset=offset, returning_size=len(trimmed_content))
                return trimmed_content

            self._logger.debug("Returning all bytes", size=len(content_to_return))
            return content_to_return

    @traced
    def readdir(self, path: str, offset: int) -> Generator[fuse.Direntry, None, None] | int:
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        with structlog.contextvars.bound_contextvars(path=path):
            self._logger.debug("readdir", offset=offset)

            resource = self.hierarchy.get_resource_by_path(path)
            if not isinstance(resource, Container):
                raise Exception(f"{resource.uri} is not a Solid Container so we cannot 'readdir' on it")

            with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
                contained_resources = self.hierarchy.get_contained_resources(resource)
                yield from [fuse.Direntry(r) for r in [".", ".."]]

                for contained_resource in contained_resources:
                    # We need to strip the terminating slash off Containers because fuse crashes if they are included
                    name = str(URIRefHelper.relative_to(resource.uri, contained_resource.uri)).rstrip("/")
                    self._logger.debug("Returning directory entry", name=name, uri=resource.uri)
                    dir_entry = fuse.Direntry(name)

                    if isinstance(contained_resource, Resource):
                        dir_entry.type = stat.S_IFREG
                    if isinstance(contained_resource, Container):
                        dir_entry.type = stat.S_IFDIR

                    assert dir_entry.type
                    yield dir_entry

    @traced
    def rename(self, source: str, target: str) -> int:

        validation_code = SolidPathValidation.get_path_validation_result_code(source)
        if validation_code:
            return -validation_code

        validation_code = SolidPathValidation.get_path_validation_result_code(target)
        if validation_code:
            return -validation_code

        self._logger.debug("rename", source=source, target=target)

        source_resource = self.hierarchy.get_resource_by_path(source)
        content = self.read(source, source_resource.stat.st_size, 0)
        if isinstance(content, int):
            return -content

        self.create(target, source_resource.stat.st_mode, None)
        self.write(target, content, 0)
        self.unlink(source)
        return 0

    @traced
    def rmdir(self, path: str):
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code
        self._logger.debug("rmdir", path=path)
        self.unlink(path)

    @traced
    def truncate(self, path: str, size: int) -> int:
        """Change the size of a file"""

        # http://libfuse.github.io/doxygen/structfuse__operations.html#a73ddfa101255e902cb0ca25b40785be8

        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        assert not path.endswith("/")
        assert size >= 0
        self._logger.debug("truncate", path=path, size=size)
        resource = self.hierarchy.get_resource_by_path(path)

        if size:
            if resource.content.get() is None:
                self.read(path, size, 0)
            content = resource.content.get()
            if content is None:
                raise Exception(f"Resource content for {resource.uri} is missing")

            if len(content) < size:
                raise Exception(f"Unable to set size of {resource.uri} to {size} as there is only {len(content)} bytes of content to put in it")
            current_size = len(content)
        else:
            # We don't have an opinion about the current information
            # There will be a bug later here when someone tries to stop it writing when the target is already zero-length but it only looks like it's zero-length but is in fact unknown so the current bytes will stay there
            content = bytes()
            current_size = -1

        if size != current_size:
            new_content = content[:size]
            resource.content.set(new_content)
            resource.stat.st_size = size
            # Don't change the content type
            self.write(path, new_content, 0)
        return 0

    @traced
    def unlink(self, path: str) -> int:
        """Delete a Resource"""

        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

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

    @traced
    def utime(self, path: str, times: tuple[int, int]) -> int:
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        self._logger.warning("Unable to set times on Solid Resource", path=path, times=times)
        return 0

    @traced
    def write(self, path: str, buf: bytes, offset: int) -> int:
        """Write a Resource"""
        validation_code = SolidPathValidation.get_path_validation_result_code(path)
        if validation_code:
            return -validation_code

        assert isinstance(buf, bytes)
        self._logger.debug("write", path=path, size=len(buf), offset=offset)

        with structlog.contextvars.bound_contextvars(path=path):
            resource = self.hierarchy.get_resource_by_path(path)
            existing_content = bytes()
            if offset != 0:
                existing_content = resource.content.get()
                if existing_content is None:
                    try:
                        self._logger.debug("Reading existing bytes")
                        read_result = self.read(path, 10000000, 0)
                        if isinstance(read_result, int):
                            return -read_result
                        existing_content = read_result
                        self._logger.debug("Read existing bytes", size=len(existing_content))
                    except:
                        self._logger.warning("Unable to read existing bytes", exc_info=True)
                        existing_content = bytes()
                        pass
                    resource.content.set(existing_content)

            extra_content_length = len(buf)
            assert extra_content_length < 10**6
            previous_length = len(existing_content)
            revised_content = existing_content[:offset] + buf + existing_content[offset + len(buf) :]
            resource.content.set(revised_content)
            resource.stat.st_size = len(revised_content)

            previous_content_type = resource.content_type

            # Now we have some content we can adapt the mime type
            SolidMime.update_mime_type_from_content(offset, resource, revised_content)

            self._logger.debug(
                "Content",
                previous_content_type=previous_content_type,
                content_type=resource.content_type,
                offset=offset,
                extra_content_length=extra_content_length,
                previous_length=previous_length,
                new_content_length=resource.stat.st_size,
            )
            headers = {"Content-Type": resource.content_type, "Content-Length": str(len(revised_content))}

            try:
                if resource.content_type != previous_content_type:
                    # If content type varies then some Solid servers won't alter their view of the content so we have to DELETE the old content first
                    # Don't use unlink because it will remove meta data
                    self._logger.info("Deleting due to content type changing", previous_content_type=previous_content_type, content_type=resource.content_type)
                    response = self.requestor.request("DELETE", resource.uri.toPython())

                response = self.requestor.request("PUT", resource.uri.toPython(), headers, revised_content)

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
