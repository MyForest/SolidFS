#!/usr/bin/env python3
import email.utils
import errno
import functools
import stat
import uuid
from stat import S_IFDIR, S_IFREG
from typing import Generator

import fuse
import structlog
from fuse import Fuse
from rdflib.term import URIRef

from observability.app_logging import AppLogging
from observability.tracing import Tracing
from solid_mime import SolidMime
from solid_path_validation import SolidPathValidation
from solid_request import SolidRequest
from solid_resource import Container, Resource, ResourceStat, URIRefHelper
from solid_websocket.solid_websocket import SolidWebsocketDaemon
from solidfs_resource_hierarchy import SolidResourceHierarchy

fuse.fuse_python_api = (0, 2)


class Decorators:

    @staticmethod
    def log_not_supported(func):
        """Indicates the method isn't supported, but will return as though it succeeded"""

        @functools.wraps(func)
        def wrapper(*args, **kwarg):
            scalar_args = [arg for arg in args if type(arg) in [int, str, bool]]
            logger = structlog.getLogger(SolidFS.__name__)
            logger.warning("Not supported", function_name=func.__name__, scalar_args=scalar_args)
            return 0

        return wrapper

    @staticmethod
    def add_path_to_logging_context(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with structlog.contextvars.bound_contextvars(path=args[1]):
                return func(*args, **kwargs)

        return wrapper

    @staticmethod
    def log_invocation_with_scalar_args(func):
        """Limit the logging to scalar arguments so we don't overwhelm the logger"""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with structlog.contextvars.bound_contextvars(function_name=func.__name__):
                scalar_args = [arg for arg in args if type(arg) in [int, str, bool]]
                logger = structlog.getLogger(SolidFS.__name__)
                logger.debug(func.__name__, scalar_args=scalar_args)
                return func(*args, **kwargs)

        return wrapper


class SolidFS(Fuse):
    """SolidFS is a FUSE driver for Solid"""

    def __init__(self, *args, **kw):
        session_identifier = uuid.uuid4().hex
        self._logger = structlog.getLogger(self.__class__.__name__).bind(session_identifier=session_identifier)
        self.requestor = SolidRequest(session_identifier)
        self.hierarchy = SolidResourceHierarchy(self.requestor)

        Fuse.__init__(self, *args, **kw)
        self.fd = 0

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

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def getattr(self, path: str) -> fuse.Stat | int:
        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resource_url=resource.uri):
            if resource.stat.st_mtime == 0:
                self._refresh_resource_stat(resource)
        return resource.stat

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def getxattr(self, path: str, name: str, size: int) -> str | int:
        if name == "user.mime_type":
            resource = self.hierarchy.get_resource_by_path(path)
            attribute_value = resource.content_type
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

        attribute_list = ["user.mime_type"]
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
    @Decorators.log_not_supported
    def open(self, path: str, flags) -> int:
        pass

    @Tracing.traced
    @SolidPathValidation.validate_path
    @Decorators.add_path_to_logging_context
    @Decorators.log_invocation_with_scalar_args
    @SolidPathValidation.customize_return_based_on_exception_type
    def read(self, path: str, size: int, offset: int) -> bytes | int:

        resource = self.hierarchy.get_resource_by_path(path)
        with structlog.contextvars.bound_contextvars(resource_url=resource.uri):

            self._logger.debug(f"Fetching", size=size, uri=resource.uri)

            # Note that we're not using a ranged request because fuse asks for very small chunks and the overhead of fetching them is large
            # Specifically, the largest read size as at 2024-04-13 is 131072 bytes.
            response = self.requestor.request("GET", resource.uri.toPython(), {"Accept": "*"})

            if response.status_code == 200:
                content_to_return = response.content
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
                    self._logger.debug(f"Unable to set size as there are not enough bytes of content to put in it", available_bytes=len(content))
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
        """Write a Resource"""

        assert isinstance(buf, bytes)

        resource = self.hierarchy.get_resource_by_path(path)
        existing_content = bytes()
        if offset != 0:
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

        extra_content_length = len(buf)
        assert extra_content_length < 10**6
        previous_length = len(existing_content)
        revised_content = existing_content[:offset] + buf + existing_content[offset + len(buf) :]
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
        return -errno.EBADMSG


if __name__ == "__main__":
    AppLogging.configure_logging()
    SolidWebsocketDaemon().start()

    usage = (
        """
SolidFS enables a file system interface to a Solid Pod
"""
        + Fuse.fusage
    )
    server = SolidFS(version="%prog " + fuse.__version__, usage=usage, dash_s_do="setsingle")

    server.parser.add_option(mountopt="root", metavar="PATH", default="/data/", help="Surface Pod at PATH [default: %default]")
    server.parse(errex=1)

    # Now let fuselib have the main thread any other threads it wants, but also keep the executor context so the websocket thread doesn't get stopped
    server.main()
