from __future__ import annotations

from typing import Any, Mapping

class RequestException(Exception):
    pass

class HTTPError(RequestException):
    response: Response | None

    def __init__(
        self,
        *args: Any,
        response: Response | None = None,
        request: Any | None = None,
    ) -> None: ...

class Response:
    status_code: int
    headers: Mapping[str, Any]
    text: str

    def raise_for_status(self) -> None: ...
    def json(self) -> Any: ...

def get(*args: Any, **kwargs: Any) -> Response: ...
def post(*args: Any, **kwargs: Any) -> Response: ...
def put(*args: Any, **kwargs: Any) -> Response: ...
