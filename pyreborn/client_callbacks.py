"""Multiple subscribers for the `client.on_*` callback slots.

`client.on_x = fn` stays the way an embedding app installs ITS hook: a plain
assignment, readable back, `None` to clear. A slot holds one function, so a
second subscriber (a script engine, a recorder, a debug overlay, a test probe)
used to overwrite the first or had to be forwarded to by hand. `add_listener`
adds extra subscribers beside the slot instead.

Rules, all behaviour-preserving for code that only uses slots:

* Every emission goes through `emit`. It calls the slot first (when set), then
  the listeners in registration order. It returns the SLOT's return value.
* Nothing is swallowed. An exception from the slot or a listener propagates to
  the caller (the per-packet guard in `Client.update` logs it) and the
  remaining subscribers for that emission do not run, exactly as a raising slot
  stopped everything after it before.
* A listener list is replaced, never mutated, so an emission that is running
  on another thread (RCClient/NCClient worker threads) sees a stable snapshot.
* `on_packet` is a dict of per-packet hooks, not a slot. `add_packet_listener`
  is its counterpart; see `Client.dispatch_packet_listeners`.

`emit` and `has_subscribers` are module functions taking the client first so
handlers also work against the small stand-in objects tests pass them.
"""

from typing import Callable, Dict, Tuple


def _listener_table(client) -> dict:
    # vars() rather than getattr: a Mock or namespace stand-in must read as
    # "no listeners", not auto-create a table.
    try:
        return vars(client).get('_listeners') or {}
    except TypeError:
        return {}


def has_subscribers(client, name: str, /) -> bool:
    """True when emitting `name` would call anything."""
    return bool(getattr(client, name, None)) or bool(_listener_table(client).get(name))


def emit(client, name: str, /, *args, **kwargs):
    """Call slot `name` then its listeners; return the slot's return value."""
    slot = getattr(client, name, None)
    result = slot(*args, **kwargs) if slot else None
    listeners = _listener_table(client).get(name)
    if listeners:
        for listener in listeners:
            listener(*args, **kwargs)
    return result


class CallbackMixin:
    """`Client`'s listener registry. State: `_listeners`, `_packet_listeners`."""

    def _init_callback_listeners(self) -> None:
        self._listeners: Dict[str, Tuple[Callable, ...]] = {}
        self._packet_listeners: Dict[int, Tuple[Callable, ...]] = {}

    @staticmethod
    def callback_names() -> frozenset:
        """Every callback slot name `add_listener` accepts."""
        from .client_state import Callbacks
        return frozenset(n for n in Callbacks.state_fields()
                         if n.startswith('on_') and n != 'on_packet')

    def add_listener(self, name: str, fn: Callable) -> Callable[[], None]:
        """Subscribe `fn` to callback `name` (e.g. 'on_server_text') beside
        the slot. Returns a function that removes it again (idempotent).

        Raises ValueError for a name that is not a callback slot."""
        if name not in self.callback_names():
            raise ValueError("unknown client callback %r" % (name,))
        self._listeners[name] = self._listeners.get(name, ()) + (fn,)

        def remove() -> None:
            current = self._listeners.get(name, ())
            if fn in current:
                index = current.index(fn)
                self._listeners[name] = current[:index] + current[index + 1:]
        return remove

    def add_packet_listener(self, packet_id: int, fn: Callable) -> Callable[[], None]:
        """Subscribe `fn(data)` to one inbound packet id. Runs after the
        built-in handler (and is skipped when it returns STOP), BEFORE the
        embedding app's `on_packet[packet_id]` hook. Returns a remover."""
        self._packet_listeners[packet_id] = (
            self._packet_listeners.get(packet_id, ()) + (fn,))

        def remove() -> None:
            current = self._packet_listeners.get(packet_id, ())
            if fn in current:
                index = current.index(fn)
                self._packet_listeners[packet_id] = (
                    current[:index] + current[index + 1:])
        return remove

    def emit(self, name: str, /, *args, **kwargs):
        """See module `emit`."""
        return emit(self, name, *args, **kwargs)

    def has_subscribers(self, name: str, /) -> bool:
        return has_subscribers(self, name)
