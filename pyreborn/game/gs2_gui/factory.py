from __future__ import annotations

from typing import Any, Dict

from .base import GuiControl
from .basic_controls import (
    GuiButtonCtrl, GuiTextCtrl, GuiWindowCtrl,
)
from .collection_controls import (
    GuiDrawingPanel, GuiStartMenuCtrl, GuiTabCtrl, GuiTaskbar,
    GuiTextListCtrl, GuiTreeViewCtrl,
)
from .image_controls import (
    GuiBitmapButtonCtrl, GuiBitmapCtrl, GuiCheckBoxCtrl, GuiRadioCtrl,
    GuiShowImgCtrl,
)
from .popup_controls import (
    GuiContextMenuCtrl, GuiFrameSetCtrl, GuiPopUpEditCtrl, GuiPopUpMenuCtrl,
    GuiStretchCtrl,
)
from .profiles import GuiControlProfile, _log_once
from .text_controls import (
    GuiAccountPasswordCtrl, GuiMLTextCtrl, GuiMLTextEditCtrl, GuiProgressCtrl,
    GuiScrollCtrl, GuiSliderCtrl, GuiTextEditCtrl, GuiTextEditSliderCtrl,
)
from .basic_controls import GuiButtonBaseCtrl  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from .collection_controls import GuiTreeNode, _TreeNodeIcon  # noqa: F401  - kept: original import block (star-import consumers rely on it)


_CONTROL_CLASSES: Dict[str, type] = {
    cls.CTRL_CLASS.lower(): cls for cls in (
        GuiControl, GuiWindowCtrl, GuiButtonCtrl, GuiTextCtrl, GuiMLTextCtrl,
        GuiScrollCtrl, GuiTextEditCtrl, GuiCheckBoxCtrl, GuiRadioCtrl,
        GuiBitmapCtrl, GuiShowImgCtrl, GuiPopUpEditCtrl, GuiControlProfile,
        GuiTextListCtrl, GuiTabCtrl, GuiTreeViewCtrl, GuiTaskbar,
        GuiStartMenuCtrl,
        # These classes otherwise fall back to a generic GuiControl.
        GuiAccountPasswordCtrl, GuiMLTextEditCtrl, GuiProgressCtrl,
        GuiBitmapButtonCtrl, GuiPopUpMenuCtrl, GuiDrawingPanel,
        GuiFrameSetCtrl, GuiContextMenuCtrl, GuiStretchCtrl,
        GuiSliderCtrl, GuiTextEditSliderCtrl,
    )
}


def control_method_names() -> frozenset:
    """Every script-callable control method across the whole class table."""
    names: set = set()
    for cls in (*_CONTROL_CLASSES.values(), GuiControl):
        names |= set(getattr(cls, "_METHOD_NAMES", ()))
    return frozenset(names)


def make_control(classname: str, ctor_arg: Any) -> GuiControl:
    cls = _CONTROL_CLASSES.get(classname.lower())
    if cls is None:
        if classname.lower().endswith("profile"):
            # Torque profile-definition DERIVATION: the classname is the
            # PARENT profile (engine builtin like GuiBlueTransWindowProfile,
            # or a previously script-defined profile like IRC_WindowProfile)
            # and roots the new profile's inheritance chain. Named style
            # records, never visual controls -- Login's -Rescripted/
            # Serverlist declares ~40 of these.
            ctrl = GuiControlProfile(ctor_arg, parent_name=classname)
            # The object's script-facing name is its own REGISTERED name,
            # not the parent's: the reference object/string compare row is
            # strcasecmp(var->name, string) (TScriptMachine::compare
            # String/Null rows, asm-verified), so `x.profile ==
            # "IRC_WindowLeftProfile"` must see the derived profile's own
            # name. Anonymous derivations keep the parent name.
            ctrl.name = (ctor_arg if isinstance(ctor_arg, str) and ctor_arg
                         else classname)
            return ctrl
        _log_once(("class", classname.lower()),
                  "GS2 GUI: unknown control class %r, rendering generically", classname)
        ctrl = GuiControl(ctor_arg)
        ctrl.name = classname
        return ctrl
    return cls(ctor_arg)
