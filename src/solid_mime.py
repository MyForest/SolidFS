import mimetypes

import magic

from solid_resource import Resource


class SolidMime:

    @staticmethod
    def update_mime_type_from_content(offset: int, resource: Resource, content: bytearray) -> None:
        """Guesses the mime type and records it on the resource"""
        if offset >= 1024:
            # content type is based on just a few bytes or file extension so it won't change if writing later bytes
            return

        if len(content):
            try:
                magic_mime = magic.from_buffer(bytes(content[:1024]), mime=True)
                if magic_mime:
                    resource.content_type = magic_mime
            except:
                # Could not determine mime type from bytes
                pass
        else:
            # content type can't be determined when there is no content so leave it unchanged
            pass

    @staticmethod
    def update_mime_type_from_uri(resource: Resource) -> None:
        """Guesses the mime type and records it on the resource"""

        type_from_extension, encoding_from_extension = mimetypes.guess_type(resource.uri, strict=False)
        if type_from_extension:
            if encoding_from_extension:
                resource.content_type = f"{type_from_extension};charset={encoding_from_extension}"
            else:
                resource.content_type = type_from_extension
