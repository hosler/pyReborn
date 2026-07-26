"""Compatibility namespace for the GS2 GUI-controls rendering package."""
from __future__ import annotations

from . import profiles as _profiles
from . import (
    base as _base,
    factory as _factory,
    manager as _manager,
    mltext as _mltext,
    skins as _skins,
)

_MODULES = (
    _profiles, _skins, _mltext, _base, _factory, _manager,
)
_NAMES = (
    "Any", "Dict", "GS2GuiManager", "GS2Object", "GuiAccountPasswordCtrl",
    "GuiBitmapButtonCtrl", "GuiBitmapCtrl", "GuiButtonBaseCtrl",
    "GuiButtonCtrl", "GuiCheckBoxCtrl", "GuiContextMenuCtrl", "GuiControl",
    "GuiControlProfile", "GuiDrawingPanel", "GuiFrameSetCtrl", "GuiListRow",
    "GuiMLTextCtrl", "GuiMLTextEditCtrl", "GuiPopUpEditCtrl",
    "GuiPopUpMenuCtrl", "GuiProfile", "GuiProgressCtrl", "GuiRadioCtrl",
    "GuiScrollCtrl", "GuiShowImgCtrl", "GuiStartMenuCtrl", "GuiStretchCtrl",
    "GuiTabCtrl", "GuiTaskbar", "GuiTextCtrl", "GuiTextEditCtrl",
    "GuiTextListCtrl", "GuiTreeNode", "GuiTreeViewCtrl", "GuiWindowCtrl", "List",
    "Optional", "Tuple", "_ALIGNMENTS", "_BEVEL_DARK", "_BEVEL_LIGHT",
    "_BLUE_FILL", "_BLUE_HL", "_BUILTIN_PROFILE_FIELDS", "_CONTROL_CLASSES",
    "_DEFAULT_GUIPROFILE", "_DEFAULT_PROFILE_NAME", "_InertDrawable",
    "_MAX_PARENT_DEPTH", "_MAX_PROFILE_CHAIN", "_MLSegment", "_ML_ENTITIES",
    "_ML_FONT_SIZES", "_ML_HEADING_SIZES", "_ML_LINK_COLOR", "_ML_TOKEN_RE",
    "_PALE_TEXT", "_STYLE_ALIASES", "_STYLE_FIELDS", "_Skin", "_TreeNodeIcon",
    "_color", "_draw_border", "_draw_label", "_fill_rect", "_font", "_log_once",
    "_logged_once", "_ml_parse_color", "_profile_fields",
    "_profile_from_fields", "_readable_on", "_shade", "_split_bitmap_array",
    "_wrap_text", "annotations", "control_method_names", "logger", "logging",
    "make_control", "parse_mltext", "pygame", "to_bool", "to_num", "to_str",
)

for _name in _NAMES:
    for _module in _MODULES:
        if hasattr(_module, _name):
            globals()[_name] = getattr(_module, _name)
            break

__all__ = _NAMES
_ORIGINAL_DIR = tuple(sorted((*_NAMES, "__annotations__", "__builtins__",
                              "__cached__", "__doc__", "__file__", "__loader__",
                              "__name__", "__package__", "__spec__")))


def __dir__():
    return list(_ORIGINAL_DIR)
