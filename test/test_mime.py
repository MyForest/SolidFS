import sys
import tempfile
from pathlib import Path

import xattr

# Use a test folder so we don't pollute the Pod too much
test_root_folder = Path("/data") / "test/"


def test_replace_with_different_content_type():
    """Simply checking for exceptions when invoking methods"""
    text_plain = "Plain text"
    text_html = "<html><head><title>HTML</title></head></html>"

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8") as temp_file:
        temp_file.write(text_plain)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == text_plain

        temp_file.truncate(0)
        temp_file.write(text_html)
        temp_file.flush()

        with open(temp_file.name) as source:
            content = source.read()
            assert content == text_html


def test_mime_type_in_xattr_for_html():
    """The mime type is available in the extended attributes of the file so check the magic mime type detection is working reasonably"""
    text_html = "<html><head><title>HTML</title></head></html>"

    # Purposefully avoid using a file extension so it's not tempting to use it for the content type

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8") as temp_file:
        temp_file.write(text_html)
        temp_file.flush()

        assert "text/html" == xattr.xattr(temp_file.name).get("user.mime_type").decode("utf-8")
        with open(temp_file.name) as source:
            content = source.read()
            assert content == text_html


def test_mime_type_in_xattr_for_text():
    """The mime type is available in the extended attributes of the file so check the magic mime type detection is working reasonably"""
    text_plain = "Some plain text"

    # Purposefully avoid using a file extension so it's not tempting to use it for the content type

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8") as temp_file:
        temp_file.write(text_plain)
        temp_file.flush()

        assert "text/plain" == xattr.xattr(temp_file.name).get("user.mime_type").decode("utf-8")
        with open(temp_file.name) as source:
            content = source.read()
            assert content == text_plain


def test_mime_type_in_xattr_for_empty():
    """The mime type is available in the extended attributes of the file so check the magic mime type detection is working reasonably"""
    text_plain = "Some plain text"

    # Purposefully avoid using a file extension so it's not tempting to use it for the content type

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+t", encoding="utf-8") as temp_file:
        temp_file.flush()

        assert "application/octet-stream" == xattr.xattr(temp_file.name).get("user.mime_type").decode("utf-8")
        with open(temp_file.name) as source:
            content = source.read()
            assert len(content) == 0


def xtest_mime_type_in_xattr_for_png():
    """The mime type is available in the extended attributes of the file so check the magic mime type detection is working reasonably"""

    png = b"\x89" + "PNG\r\n\x1A\n".encode("ascii")

    # Purposefully avoid using a file extension so it's not tempting to use it for the content type

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+b") as temp_file:
        temp_file.write(png)
        temp_file.flush()

        assert "image/png" == xattr.xattr(temp_file.name).get("user.mime_type").decode("utf-8")
        with open(temp_file.name, "r+b") as source:
            content = source.read()
            assert content == png


def test_mime_type_in_xattr_for_png_from_file_extension():
    """The mime type is available in the extended attributes of the file so check the mimetype detection is working reasonably"""

    with tempfile.NamedTemporaryFile(dir=test_root_folder, prefix=sys._getframe().f_code.co_name, mode="w+b", suffix=".png") as temp_file:
        temp_file.flush()

        assert "image/png" == xattr.xattr(temp_file.name).get("user.mime_type").decode("utf-8")