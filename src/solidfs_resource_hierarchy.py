#!/usr/bin/env python3
from asyncio import AbstractEventLoop
import os
import stat
from stat import S_IFDIR
from time import time
from typing import Iterable

import structlog
from rdflib import Graph
from rdflib.term import URIRef

from solid_request import ResourceNotFoundException, SolidRequest
from solid_resource import Container, Resource, ResourceStat, URIRefHelper
from solid_websocket import SolidWebsocket


class SolidResourceHierarchy:
    """A Solid Pod is a Resource hierarchy with Containers representing the branches and non-Containers as the leaves"""

    def __init__(self, requestor: SolidRequest, websocket_event_loop:AbstractEventLoop):
        self._logger = structlog.getLogger(self.__class__.__name__)

        self.root: Container | None = None
        self.requestor = requestor
        self.websocket_event_loop = websocket_event_loop
        self.now = time()

    def _get_root(self) -> Container:
        """Return the Container representing the root of the hierarchy"""
        if self.root is None:
            base_url = os.environ.get("SOLIDFS_BASE_URL")
            if base_url is None:
                self._logger.exception("Please set the 'SOLIDFS_BASE_URL'")
                raise Exception("Please set the 'SOLIDFS_BASE_URL'")
            self._logger.info("Establishing root", base_url=base_url)
            self.root = Container(URIRef(base_url) + "/", ResourceStat(mode=S_IFDIR | 0o777, nlink=2))

        return self.root

    def get_resource_by_path(self, relative_path: str, start: Resource | None = None) -> Resource:
        """Map a file-system path, delimited by /, to a Resource's URI"""

        if relative_path in ["/", ""]:
            return self._get_root()

        if start is None:
            start = self._get_root()

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
                raise ResourceNotFoundException(f"'{part}' not found in '{current.uri}' when looking for '{relative_path}' from '{start.uri}'")

        return current

    def get_contained_resources(self, container: Container) -> Iterable[Resource]:
        """Return the child Resources of this Container in the hierarchy"""
        with structlog.contextvars.bound_contextvars(resource_url=container.uri):
            if container.contains is None:
                quoted_url = URIRefHelper.to_quoted_url(container.uri)
                self._logger.debug("Determining contents of Container", quoted_url=quoted_url)

                response = self.requestor.request("GET", quoted_url, {"Accept": "text/turtle,application/rdf+xml,application/ld+json"})

                if response.status_code == 200:
                    content = response.content
                    self._logger.debug("Parsing Container RDF", size=len(content))
                    g = Graph()
                    g.parse(data=content, publicID=container.uri)
                    # The URIs in the graph are quoted, but our in-memory URIs are UTF-8 encoded strings in URIRefs which aren't quoted
                    ldp_contained = list(g.objects(URIRef(URIRefHelper.to_quoted_url(container.uri)), URIRef("http://www.w3.org/ns/ldp#contains")))

                    items = set[Resource]()
                    self._logger.debug("Contains", size=len(ldp_contained))
                    for quoted_resource in ldp_contained:
                        if not isinstance(quoted_resource, URIRef):
                            raise Exception(f"Expected {quoted_resource} to be a URIRef but it was {type(quoted_resource)}")
                        resource = URIRefHelper.from_quoted_url(quoted_resource.toPython())
                        self._logger.debug("Discovered contained Resource", uri=resource)
                        if str(resource).endswith("/"):
                            discovered_resource = Container(resource, ResourceStat(mode=stat.S_IFDIR | 0o755, nlink=2))
                        else:
                            discovered_resource = Resource(resource, ResourceStat(size=1000000, mode=stat.S_IFREG | 0o444))

                        SolidWebsocket.listen_for_notifications(self.requestor, discovered_resource, self.websocket_event_loop)
                        items.add(discovered_resource)

                    container.contains = items
                else:
                    raise Exception(f"Error fetching Solid resource {container.uri} with code {response.status_code}: {response.text}")

            return container.contains

    def get_parent(self, path: str) -> Container:
        """Get the Container that contains the Resource represented by the path"""
        parts = path.split("/")
        container = self.get_resource_by_path("/".join(parts[:-1]))
        if not isinstance(container, Container):
            raise Exception(f"Parent of {path} is not a Container. It is at {container.uri}")
        return container
