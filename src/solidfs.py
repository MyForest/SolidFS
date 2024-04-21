#!/usr/bin/env python3
import email.utils
import errno
import os
import stat
import uuid
from stat import S_IFDIR, S_IFREG
from typing import Generator

import fuse
import structlog
from dotenv import load_dotenv
from fuse import Fuse
from rdflib.term import URIRef

from decorators import Decorators
from http_exception import HTTPStatusCodeException
from observability.app_logging import AppLogging
from observability.tracing import Tracing
from solid_mime import SolidMime
from solid_path_validation import SolidPathValidation
from solid_requestor import SolidRequestor, requestor_daemon
from solid_resource import (
    Container,
    ExtendedAttribute,
    Resource,
    ResourceStat,
    URIRefHelper,
)
from solid_websocket.solid_websocket import websocket_daemon
from solidfs_resource_hierarchy import SolidResourceHierarchy

fuse.fuse_python_api = (0, 2)


class SolidFS(Fuse):
    """SolidFS is a FUSE driver for Solid"""

    def __init__(self, *args, **kw):
        session_identifier = uuid.uuid4().hex
        self._logger = structlog.getLogger(self.__class__.__name__).bind(session_identifier=session_identifier)
        self.requestor = self.set_up_requestor(session_identifier)
        self.hierarchy = SolidResourceHierarchy(self.requestor)
        self.resource_write_buffer: dict[URIRef, bytearray] = {}

        self.resource_read_buffer: dict[URIRef, bytes] = {}
        """A bad cache that grows indefinitely"""

        Fuse.__init__(self, *args, **kw)
        self.fd = 0

    def set_up_requestor(self, session_identifier: str) -> SolidRequestor:
        match os.environ.get("SOLIDFS_HTTP_LIBRARY"):
            case "httpx":
                from solid_httpx import SolidHTTPX

                return SolidHTTPX(session_identifier)
            case _:
                # Specify a default so people don't have to worry about it until they want to
                from solid_request import SolidRequest

                return SolidRequest(session_identifier)

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.log_not_supported
    def chmod(self, path: str, mode: int) -> int:
        pass

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.log_not_supported
    def chown(self, path: str, uid, gid) -> int:
        pass

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def create(self, path: str, mode, umask) -> int:
        """Create a Resource"""

        parent, name = path.rsplit("/", 1)
        container = self.hierarchy.get_resource_by_path(parent)
        if not isinstance(container, Container):
            self._logger.info("Parent is not a Solid Container", parent=container)
            return -errno.ENOTDIR

        resource_url = container.uri + URIRef(name)
        new_resource = Resource(resource_url, ResourceStat(0, S_IFREG | 0o777))
        # The URI doesn't change after creation so we can make an attempt to guess the content type on creation
        SolidMime.update_mime_type_from_uri(new_resource)

        headers = {
            "Link": '<http://www.w3.org/ns/ldp#Resource>; rel="type"',
            "Content-Type": new_resource.content_type,
        }

        with structlog.contextvars.bound_contextvars(resource_url=resource_url):
            self._logger.info("Creating Solid Resource", parent=parent, name=name, mode=mode, content_type=new_resource.content_type)
            # Use PUT so the name on the server matches the requested path
            response = self.requestor.request("PUT", resource_url.toPython(), headers)

            if response.status_code in [201, 204]:

                if container.contains is None:
                    container.contains = set()
                container.contains.add(new_resource)
                return 0

            self._logger.error(f"Error creating Solid Resource on server", status_code=response.status_code, text=response.content, exc_info=True)
            return -errno.EBADMSG

    @Decorators.log_invocation_with_scalar_args
    def _refresh_resource_stat(self, resource: Resource) -> None:

        try:
            response = self.requestor.request(
                "HEAD",
                resource.uri.toPython(),
                {"Accept": "*"},
            )
        except HTTPStatusCodeException as http_exception:
            self._logger.warning("Unable to refresh stats", exception_message=http_exception.message, resource_url=resource.uri, status_code=http_exception.http_response_code)
            return
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

        headers_to_reflect_in_extended_attributes = ["allow"]

        # TODO: If you just readdir the root you don't get the triples from the contains
        if resource == self.hierarchy._get_root():
            headers_to_reflect_in_extended_attributes.append("X-Powered-By")

        try:
            for header in headers_to_reflect_in_extended_attributes:
                if header in response.headers:
                    resource.extended_attributes[f"user.header.{header.lower()}"] = ExtendedAttribute("headers", response.headers.get(header, ""))
        except:
            self._logger.warning("Unable to add headers to extended attributes", exc_info=True)

        try:
            for rel, d in response.links.items():
                resource.extended_attributes[f"user.link.{rel.lower()}"] = ExtendedAttribute("links", d.get("url", ""))
        except:
            self._logger.warning("Unable to add links to extended attributes", exc_info=True)

        if "Content-Type" in response.headers:
            resource.extended_attributes["user.mime_type"] = ExtendedAttribute("headers", response.headers["Content-Type"])
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

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def getattr(self, path: str) -> fuse.Stat | int:
        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
            if resource.stat.st_mtime == 0 or resource.stat.st_mode == 0:
                self._refresh_resource_stat(resource)
            self._logger.debug("Stats", **vars(resource.stat))
        return resource.stat

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def getxattr(self, path: str, name: str, size: int) -> str | int:
        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
            extended_attribute = resource.extended_attributes.get(name)
            if extended_attribute:
                attribute_value = extended_attribute.value
                if size == 0:
                    # We are asked for size of the value.
                    return len(attribute_value)
                return attribute_value

        return 0

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def listxattr(self, path: str, size: int) -> list | int:
        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
            attribute_list = [str(k) for k in resource.extended_attributes.keys()]
            if size == 0:
                # We are asked for size of the attr list, i.e. joint size of attrs
                # plus null separators.
                return len("".join(attribute_list)) + len(attribute_list)
            return attribute_list

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    def mkdir(self, path: str, mode) -> int:
        """Create a Container"""
        # TODO: Understand nlink
        # TODO: Use mode

        if path.endswith("/"):
            # Peculiarly, the path does not typically arrive with a slash at the end and we make assumptions based on that so let's enforce it
            self._logger.warn("Unexpected slash at end of path", path=path)
            return -errno.EINVAL

        parent, name = path.rsplit("/", 1)
        parent_container = self.hierarchy.get_resource_by_path(parent)
        if not isinstance(parent_container, Container):
            self._logger.warn("Parent is not a Container", parent_container_url=parent_container.uri)
            return -errno.ENOTDIR

        with structlog.contextvars.bound_contextvars(parent_container_url=parent_container.uri, name=name):

            target_uri = parent_container.uri + URIRef(name + "/")
            quoted_url = URIRefHelper.to_quoted_url(target_uri)
            self._logger.info("Creating Solid Container", target_uri=target_uri, quoted_url=quoted_url)
            headers = {
                "Link": '<http://www.w3.org/ns/ldp#BasicContainer>; rel="type"',
                "Content-Type": "text/turtle",
            }

            response = self.requestor.request("PUT", quoted_url, headers)
            if response.status_code in [201, 204]:
                new_container = Container(target_uri, ResourceStat(mode=S_IFDIR | 0o777, nlink=2), content_type="text/turtle")
                if parent_container.contains is None:
                    parent_container.contains = set()
                parent_container.contains.add(new_container)

                return 0

            self._logger.error(f"Error creating Solid Container on server", status_code=response.status_code, text=response.text, exc_info=True)
            return -errno.EBADMSG

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def open(self, path: str, flags) -> int:
        is_append_set = flags & os.O_APPEND == os.O_APPEND

        if is_append_set:
            self._logger.warning("Append is not yet supported")
            raise Exception("We don't support append yet")
        pass

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def read(self, path: str, size: int, offset: int) -> bytes | int:

        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resource_url=resource.uri, size=size, offset=offset):

            self._logger.debug(f"Fetching", size=size, uri=resource.uri)

            # Note that we're not using a ranged request because fuse asks for very small chunks and the overhead of fetching them is large
            # Specifically, the largest read size as at 2024-04-13 is 131072 bytes.

            if offset:
                # We have to read all of a Resource so there's no point asking the server if this later part of the Resource has changed because we already have the answer from the offset=0 request
                cached = self.resource_read_buffer.get(resource.uri)
                if cached:
                    content_to_return = cached[offset : offset + size]
                    self._logger.debug("Returning content from read cache", returning_size=len(content_to_return), from_cache=True)
                    return content_to_return

            response = self.requestor.request("GET", resource.uri.toPython(), {"Accept": "*"})

            if response.status_code != 200:
                raise Exception(f"Error reading Solid resource {resource.uri} with code {response.status_code}: {response.text}")

            content_length = len(response.content)
            content_to_return = response.content[offset : offset + size]
            if offset == 0:
                resource.content_type = response.headers["Content-Type"]
                resource.extended_attributes["user.mime_type"] = ExtendedAttribute("headers", response.headers["Content-Type"])
                resource.stat.st_size = content_length
                self.resource_read_buffer[resource.uri] = response.content

            self._logger.debug("Returning content", returning_size=len(content_to_return))
            return content_to_return

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def readdir(self, path: str, offset: int) -> Generator[fuse.Direntry, None, None] | int:

        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
            if not isinstance(resource, Container):
                self._logger.debug("Not a Solid Container so we cannot 'readdir' on it")
                return -errno.ENOTDIR

            contained_resources = self.hierarchy.get_contained_resources(resource)
            yield from [fuse.Direntry(r) for r in [".", ".."]]

            for contained_resource in contained_resources:
                # We need to strip the terminating slash off Containers because fuse crashes if they are included
                name = str(URIRefHelper.relative_to(resource.uri, contained_resource.uri)).rstrip("/")
                self._logger.debug("Returning directory entry", name=name)
                dir_entry = fuse.Direntry(name)

                if isinstance(contained_resource, Resource):
                    dir_entry.type = stat.S_IFREG
                if isinstance(contained_resource, Container):
                    dir_entry.type = stat.S_IFDIR

                assert dir_entry.type
                yield dir_entry

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def flush(self, path: str) -> int:
        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
            content = self.resource_write_buffer.get(resource.uri)

            if content is None:
                self._logger.debug("No content in buffer")
                return 0

            content_length = len(content)
            previous_content_type = resource.content_type
            SolidMime.update_mime_type_from_content(0, resource, content)

            expected_put_response_code = 204
            if resource.content_type != previous_content_type:
                # If content type varies then some Solid servers won't alter their view of the content so we have to DELETE the old content first
                # Don't use unlink because it will remove meta data
                self._logger.info("Deleting due to content type changing", previous_content_type=previous_content_type, content_type=resource.content_type)
                response = self.requestor.request("DELETE", resource.uri.toPython())
                expected_put_response_code = 201

            headers = {"Content-Type": resource.content_type, "Content-Length": str(content_length)}
            self._logger.info("Writing Resource content from buffer", content_length=content_length, previous_content_type=previous_content_type, **headers)
            response = self.requestor.request("PUT", resource.uri.toPython(), headers, content)
            if response.status_code == expected_put_response_code:
                self._logger.debug("Wrote bytes to Solid server", content_length=content_length, status_code=response.status_code)
                resource.stat.st_size = content_length
            del self.resource_write_buffer[resource.uri]

            return 0

    @Tracing.traced
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def rename(self, source: str, target: str) -> int:

        source_validation_code = SolidPathValidation.get_path_validation_result_code(source)
        if source_validation_code:
            return -source_validation_code

        target_validation_code = SolidPathValidation.get_path_validation_result_code(target)
        if target_validation_code:
            return -target_validation_code

        with structlog.contextvars.bound_contextvars(source=source, target=target):
            source_resource = self.hierarchy.get_resource_by_path(source)
            read_response = self.read(source, source_resource.stat.st_size, 0)
            if isinstance(read_response, int):
                if read_response < 0:
                    return read_response
                else:
                    raise Exception(f"Unexpected read response {read_response}")
            content: bytes = read_response

            create_response = self.create(target, source_resource.stat.st_mode, None)
            if create_response < 0:
                return create_response

            write_response = self.write(target, content, 0)
            if write_response < 0:
                return write_response

            unlink_response = self.unlink(source)
            if unlink_response < 0:
                return unlink_response

        return 0

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def rmdir(self, path: str) -> int:
        return self.unlink(path)

    @Tracing.traced
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def statfs(self) -> fuse.StatVfs | int:
        # Use the maximum size for all the unknown limitations
        chunk_128KiB = 131072
        return fuse.StatVfs(
            f_bsize=chunk_128KiB,
            f_frsize=chunk_128KiB,
            f_blocks=2**32,
            f_bfree=2**32,
            f_bavail=2**32,
            f_files=2**32,
            f_ffree=2**32,
            f_favail=2**32,
            f_flag=os.ST_NOATIME | os.ST_NODIRATIME,
            f_namemax=1024,
        )

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def truncate(self, path: str, size: int) -> int:
        """Change the size of a file"""

        # http://libfuse.github.io/doxygen/structfuse__operations.html#a73ddfa101255e902cb0ca25b40785be8

        if path.endswith("/"):
            self._logger.debug("Path unexpectedly ends in a /")
            return -errno.EINVAL

        if size < 0:
            self._logger.debug("Size is less than zero", size=size)
            return -errno.EINVAL

        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resouce_url=resource.uri):
            in_flight = self.resource_write_buffer.get(resource.uri)
            if in_flight:
                self._logger.debug("Truncating in-flight buffer", old_size=len(in_flight), new_size=size)
                self.resource_write_buffer[resource.uri] = in_flight[:size]
                resource.stat.st_size = size
                # TODO: What about content type?
                return 0

            if size:
                # Add 1 to the size so we can tell if it's bigger
                # TODO: We should just ask for the size
                read_result = self.read(path, size + 1, 0)
                if isinstance(read_result, int):
                    if read_result < 0:
                        return read_result
                    else:
                        raise Exception(f"read result was unexpectedly {read_result}")
                content = read_result
                if len(content) < size:
                    self._logger.debug(f"Unable to set size as there are not enough bytes of content to put in it", available_bytes=len(content), size=size)
                    # Arguably we could pad it with zeroes
                    return -errno.EINVAL
                current_size_is_at_least = len(content)
            else:
                # We don't have an opinion about the current information
                # There will be a bug later here when someone tries to stop it writing when the target is already zero-length but it only looks like it's zero-length but is in fact unknown so the current bytes will stay there
                content = bytes()
                current_size_is_at_least = -1

            if size != current_size_is_at_least:
                self._logger.debug("Truncating because current size is not the desired size", size=size, current_size_is_at_least=current_size_is_at_least)
                new_content = content[:size]
                resource.stat.st_size = size
                # Don't change the content type
                write_result = self.write(path, new_content, 0)
                if write_result < 0:
                    return write_result
            else:
                self._logger.debug("Not truncating because the current size is already correct", size=size, current_size_is_at_least=current_size_is_at_least)
            return 0

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def unlink(self, path: str) -> int:
        """Delete a Resource"""

        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resouce_url=resource.uri):
            response = self.requestor.request("DELETE", resource.uri.toPython())

            if response.status_code in [200, 204]:  # We don't support 202 yet
                parent = self.hierarchy.get_parent(path)
                if not parent.contains is None:
                    parent.contains.remove(resource)
                return 0

            self._logger.error(f"Deleting Solid Resource failed", status_code=response.status_code, text=response.text, exc_info=True)
            return -errno.EBADMSG

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.log_not_supported
    def utime(self, path: str, times: tuple[int, int]) -> int:
        pass

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def write(self, path: str, buf: bytes, offset: int) -> int:
        """Write content for Resource to an in-memory buffer"""

        assert isinstance(buf, bytes)

        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
            content_length = len(buf)
            buffer: bytearray = self.resource_write_buffer.setdefault(resource.uri, bytearray())
            self._logger.debug("Adding content to buffer", size=len(buf), offset=offset)
            target_size = offset + content_length
            current_buffer_length = len(buffer)
            if current_buffer_length < target_size:
                delta = target_size - current_buffer_length
                self._logger.debug("Extending buffer", delta=delta, target_size=target_size, current_buffer_length=current_buffer_length)
                buffer.extend(bytearray(delta))
            buffer[offset : offset + content_length] = buf
            return content_length


if __name__ == "__main__":
    load_dotenv()
    AppLogging.configure_logging()
    websocket_daemon.start()
    requestor_daemon.start()

    usage = (
        """
SolidFS enables a file system interface to a Solid Pod
"""
        + Fuse.fusage
    )
    server = SolidFS(version="%prog " + fuse.__version__, usage=usage, dash_s_do="setsingle")
    # Set some useful defaults, they can be overridden by user-supplied command line arguments

    # Increase performance by increasing from 4KiB pages to 128KiB ones. In reality we're practically dealing with entire Resource contents as one chunk so an even larger chunk size would be preferable. We can't parallelize the work on the chunks.
    chunk_128KiB = 131072
    server.fuse_args.optdict["max_write"] = chunk_128KiB
    server.fuse_args.optdict["max_read"] = chunk_128KiB
    server.fuse_args.optlist.add("big_writes")

    server.fuse_args.optdict["max_background"] = 64

    # Always read first chunk of Resource first because we have to read it all and then we can respond to all other chunks with parts we fetched in the first request
    server.fuse_args.optlist.add("sync_read")

    server.fuse_args.optlist.add("no_remote_lock")

    # We practically always run the process synchronously so we can observe it. This may change one day.
    server.fuse_args.setmod("foreground")

    # Make the mount look nicer
    server.fuse_args.optdict["fsname"] = SolidFS.__name__

    server.parser.add_option(mountopt="root", metavar="PATH", default="/data/", help="Surface Pod at PATH [default: %default]")
    server.parse(errex=1)

    # Now let fuselib have the main thread any other threads it wants, but also keep the executor context so the websocket thread doesn't get stopped
    server.main()
