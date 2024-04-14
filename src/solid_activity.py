from enum import StrEnum

import structlog
from rdflib import RDF, Graph, URIRef


class KnownTypes(StrEnum):
    UPDATE = URIRef("https://www.w3.org/ns/activitystreams#Update")
    DELETE = URIRef("https://www.w3.org/ns/activitystreams#Delete")


class SolidActivity:
    @staticmethod
    def parse_activity(activity: str):

        logger = structlog.getLogger(SolidActivity.__name__)

        g = Graph()
        g.parse(data=activity, format="json-ld")

        # activity_id=g.objects(instance,"")

        activity_streams_object_predicate = URIRef("https://www.w3.org/ns/activitystreams#object")
        etag_predicate = URIRef("http://www.w3.org/2011/http-headers#etag")

        resources = list(g.objects(None, activity_streams_object_predicate))

        for type_of_thing in g.objects(None, RDF.type):
            if isinstance(type_of_thing, URIRef):
                for known in [k for k in KnownTypes if k.value == type_of_thing.toPython()]:
                    with structlog.contextvars.bound_contextvars(activity_type=known):
                        for resource in resources:
                            with structlog.contextvars.bound_contextvars(resource_url=resource):
                                if known == KnownTypes.UPDATE:
                                    logger.info("Should update cache")

                                if known == KnownTypes.DELETE:
                                    logger.info("Should remove")
