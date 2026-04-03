"""Handler registry - maps command type strings to handler functions."""

from typing import Callable, Optional

_HANDLERS: dict[str, Callable] = {}


def register_handler(name: str, func: Callable):
    _HANDLERS[name] = func


def get_handler(name: str) -> Optional[Callable]:
    return _HANDLERS.get(name)


# Import handler modules to trigger registration
from . import code  # noqa: F401, E402
from . import scene  # noqa: F401, E402
from . import viewport  # noqa: F401, E402
from . import materials  # noqa: F401, E402
from . import modifiers  # noqa: F401, E402
from . import io_handlers  # noqa: F401, E402
from . import animation  # noqa: F401, E402
from . import nodes  # noqa: F401, E402
from . import render  # noqa: F401, E402
from . import mesh  # noqa: F401, E402
