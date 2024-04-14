import errno


class HTTPToErrNo:
    """Maps HTTP response codes to OS level errno"""

    # HTTP status codes: https://datatracker.ietf.org/doc/html/rfc1945#autoid-43
    # errno: https://github.com/torvalds/linux/blob/master/lib/errname.c
    @staticmethod
    def http_to_errno(https_status_code: int) -> int:
        """There is such a strong correlation between Solid HTTP codes and file system codes that we can mostly determine the fuse method response from the HTTP status code"""

        match https_status_code:
            case num if 100 <= num < 200:
                # Informational
                return 0
            case num if 200 <= num < 300:
                # Successful
                return 0
            case num if 300 <= num < 400:
                # Redirection
                return errno.EREMCHG
            case 401, 403:
                return errno.EACCES
            case 404:
                return errno.ENOENT
            case 406:
                return errno.ENOTSUP
            case num if 400 <= num < 500:
                # Client Error
                return errno.EINVAL
            case num if 500 <= num < 600:
                # Server Error
                return errno.EAGAIN
            case _:
                # Unexpected HTTP status code
                return errno.EBADMSG
