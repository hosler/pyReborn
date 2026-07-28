"""Native PM window panes: GuiPMCtrl / GuiPMEditCtrl / GuiPMHistoryCtrl.

The -Playerlist weapon builds its dynamic PrivateMessage<N>_*/PMHistory<N>_*
windows around three NATIVE classes with no surviving source in any oracle
(windows spec section 8.5): a read pane whose `showPM(person)` renders the
waiting message, a reply pane whose `sendPM(person)`/`sendMassPM(persons)`
put a PLI_PRIVATEMESSAGE on the wire, and a history pane whose
`showHistory(person)` renders the local PM log
(Preagonal/gbf/bytecode/login/_Playerlist.gs2bc.gs2:2391-2805). Each is a
thin subclass over the existing ML-text controls:

- the wire behavior comes from pyReborn's own PM support
  (client.send_pm/send_pm_multi), NOT from the oracle;
- showPM's clear-on-read is an INFERENCE from the weapon reverting the
  sender's row icon right after opening when `pmswaiting()` went false
  (:2660-2674);
- the history store is the runtime's in-memory session log
  (ClientGS2.pm_history) -- the reference's on-disk log (gated by
  options.dontsavepms) is deliberately not persisted.
"""

from __future__ import annotations

from typing import Any

from reborn_protocol.gs2 import GS2Object, to_num, to_str

from .text_controls import GuiMLTextCtrl, GuiMLTextEditCtrl


def _person_id(person: Any):
    if isinstance(person, GS2Object):
        return int(to_num(person.get("id")))
    return None


class GuiPMCtrl(GuiMLTextCtrl):
    """Read pane: showPM(person) renders (and consumes) the waiting PM."""

    CTRL_CLASS = "GuiPMCtrl"
    _METHOD_NAMES = GuiMLTextCtrl._METHOD_NAMES | frozenset({"showpm"})

    def _m_showpm(self, *args) -> float:
        person = args[0] if args else None
        if not isinstance(person, GS2Object):
            return 0.0
        message = to_str(person.get("message"))
        self.text = message
        # clear-on-read (inference, see module docstring): pmswaiting()
        # must go false once the window shows the message, or the list
        # icon/flicker never resets
        person.set("message", "")
        return 0.0


class GuiPMEditCtrl(GuiMLTextEditCtrl):
    """Reply pane: sendPM(person) / sendMassPM(persons) -> PLI 28."""

    CTRL_CLASS = "GuiPMEditCtrl"
    _METHOD_NAMES = GuiMLTextEditCtrl._METHOD_NAMES | frozenset(
        {"sendpm", "sendmasspm"})

    def _rt2(self):
        return getattr(self._manager, "rt2", None)

    def _m_sendpm(self, *args) -> float:
        person = args[0] if args else None
        pid = _person_id(person)
        text = to_str(self.text)
        rt2 = self._rt2()
        client = getattr(rt2, "client", None)
        if pid is None or not text or client is None:
            return 0.0
        if getattr(client, "send_pm", None) is not None \
                and client.send_pm(pid, text):
            if getattr(rt2, "log_pm_history", None) is not None:
                rt2.log_pm_history(pid, "out", text)
            # cleared after a successful send so the reopened window
            # starts blank (inference -- no oracle shows the native
            # control's post-send state)
            self.text = ""
        return 0.0

    def _m_sendmasspm(self, *args) -> float:
        persons = args[0] if args else None
        text = to_str(self.text)
        rt2 = self._rt2()
        client = getattr(rt2, "client", None)
        if not text or client is None:
            return 0.0
        if not isinstance(persons, (list, tuple)):
            # sendMassPM(null) exists at one call site; its target set is
            # unrecovered -- conservatively a no-op rather than a guess at
            # "everyone" (flagged in the implementation report)
            return 0.0
        ids = [pid for pid in (_person_id(p) for p in persons)
               if pid is not None]
        if ids and getattr(client, "send_pm_multi", None) is not None \
                and client.send_pm_multi(ids, text):
            if getattr(rt2, "log_pm_history", None) is not None:
                for pid in ids:
                    rt2.log_pm_history(pid, "out", text)
            self.text = ""
        return 0.0


class GuiPMHistoryCtrl(GuiMLTextCtrl):
    """History pane: showHistory(person) renders the session PM log."""

    CTRL_CLASS = "GuiPMHistoryCtrl"
    _METHOD_NAMES = GuiMLTextCtrl._METHOD_NAMES | frozenset({"showhistory"})

    def _m_showhistory(self, *args) -> float:
        person = args[0] if args else None
        pid = _person_id(person)
        rt2 = getattr(self._manager, "rt2", None)
        history = getattr(rt2, "pm_history", None) or {}
        lines = []
        nick = to_str(person.get("nick")) if isinstance(person, GS2Object) \
            else ""
        for direction, text in history.get(pid, ()):
            who = "me" if direction == "out" else (nick or "them")
            lines.append(f"<b>{who}:</b> {text}")
        self.text = "\n".join(lines)
        return 0.0
