"""Every business-rule failure gets its own exception type so callers (the CLI,
tests, a future web layer) can react to the *reason* and not parse messages."""


class LibraryError(Exception):
    """Base class for everything the library raises on purpose."""


class NotFoundError(LibraryError):
    pass


class ValidationError(LibraryError):
    pass


class DuplicateError(LibraryError):
    pass


class MembershipInactiveError(LibraryError):
    pass


class UnpaidFinesError(LibraryError):
    pass


class BorrowLimitExceededError(LibraryError):
    pass


class CopyNotAvailableError(LibraryError):
    pass


class CopyReservedError(LibraryError):
    pass


class RenewalNotAllowedError(LibraryError):
    pass


class ReservationError(LibraryError):
    pass
