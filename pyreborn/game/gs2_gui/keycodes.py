from __future__ import annotations

import pygame

# =============================================================================
# pygame key -> Windows virtual-key codes for the GS2 GUI keyboard events.
#
# The reference client hands scripts `GuiEvent::getFullModifierKey(vk, mod)`:
# the Windows VK code of the key OR'd with +0x100 shift / +0x200 ctrl /
# +0x400 alt (FourPlay quattroplay/src/gui/GuiEvent.cpp:4-28), so corpus
# handlers test raw VK values (`keycode == 9` for Tab in Login's
# GraalControl.onKeyDown). pygame keys are SDL keycodes; this table maps the
# ones a desktop keyboard can produce.
# =============================================================================

_VK_SHIFTS = (0x10, 0xA0, 0xA1)      # VK_SHIFT / VK_LSHIFT / VK_RSHIFT
_VK_CTRLS = (0x11, 0xA2, 0xA3)       # VK_CONTROL / VK_LCONTROL / VK_RCONTROL
_VK_ALTS = (0x12, 0xA4, 0xA5)        # VK_MENU / VK_LMENU / VK_RMENU

_PYGAME_TO_VK = {
    pygame.K_BACKSPACE: 0x08, pygame.K_TAB: 0x09, pygame.K_CLEAR: 0x0C,
    pygame.K_RETURN: 0x0D, pygame.K_PAUSE: 0x13, pygame.K_CAPSLOCK: 0x14,
    pygame.K_ESCAPE: 0x1B, pygame.K_SPACE: 0x20,
    pygame.K_PAGEUP: 0x21, pygame.K_PAGEDOWN: 0x22,
    pygame.K_END: 0x23, pygame.K_HOME: 0x24,
    pygame.K_LEFT: 0x25, pygame.K_UP: 0x26,
    pygame.K_RIGHT: 0x27, pygame.K_DOWN: 0x28,
    pygame.K_PRINTSCREEN: 0x2C, pygame.K_INSERT: 0x2D, pygame.K_DELETE: 0x2E,
    pygame.K_KP_MULTIPLY: 0x6A, pygame.K_KP_PLUS: 0x6B,
    pygame.K_KP_MINUS: 0x6D, pygame.K_KP_PERIOD: 0x6E,
    pygame.K_KP_DIVIDE: 0x6F, pygame.K_KP_ENTER: 0x0D,
    pygame.K_NUMLOCK: 0x90, pygame.K_SCROLLLOCK: 0x91,
    pygame.K_LSHIFT: 0xA0, pygame.K_RSHIFT: 0xA1,
    pygame.K_LCTRL: 0xA2, pygame.K_RCTRL: 0xA3,
    pygame.K_LALT: 0xA4, pygame.K_RALT: 0xA5,
    # OEM punctuation, US layout
    pygame.K_SEMICOLON: 0xBA, pygame.K_EQUALS: 0xBB, pygame.K_COMMA: 0xBC,
    pygame.K_MINUS: 0xBD, pygame.K_PERIOD: 0xBE, pygame.K_SLASH: 0xBF,
    pygame.K_BACKQUOTE: 0xC0, pygame.K_LEFTBRACKET: 0xDB,
    pygame.K_BACKSLASH: 0xDC, pygame.K_RIGHTBRACKET: 0xDD,
    pygame.K_QUOTE: 0xDE,
}
# letters: VK is the UPPERCASE ASCII code
for _k in range(pygame.K_a, pygame.K_z + 1):
    _PYGAME_TO_VK[_k] = _k - pygame.K_a + 0x41
# top-row digits and the keypad
for _k in range(pygame.K_0, pygame.K_9 + 1):
    _PYGAME_TO_VK[_k] = _k - pygame.K_0 + 0x30
for _i in range(10):
    _PYGAME_TO_VK[getattr(pygame, f"K_KP{_i}")] = 0x60 + _i
# function keys F1..F15 (pygame's ceiling; VK runs to F24 = 0x87)
for _i in range(15):
    _PYGAME_TO_VK[getattr(pygame, f"K_F{_i + 1}")] = 0x70 + _i
del _k, _i


def vk_from_pygame(key: int) -> int:
    """The Windows VK code for a pygame key, 0 when unmapped."""
    return _PYGAME_TO_VK.get(key, 0)


def full_modifier_key(vk: int, pygame_mod: int) -> int:
    """GuiEvent::getFullModifierKey: each held modifier adds its bit unless
    the key itself IS that modifier."""
    out = vk
    if pygame_mod & pygame.KMOD_SHIFT and vk not in _VK_SHIFTS:
        out += 0x100
    if pygame_mod & pygame.KMOD_CTRL and vk not in _VK_CTRLS:
        out += 0x200
    if pygame_mod & pygame.KMOD_ALT and vk not in _VK_ALTS:
        out += 0x400
    return out


def torque_modifier(pygame_mod: int) -> int:
    """The mouse-event `modifier` argument: Torque SI_* modifier flags, the
    same bit groups getFullModifierKey masks (shift 0x3, ctrl 0xC, alt 0x30)."""
    out = 0
    if pygame_mod & pygame.KMOD_LSHIFT:
        out |= 0x01
    if pygame_mod & pygame.KMOD_RSHIFT:
        out |= 0x02
    if pygame_mod & pygame.KMOD_LCTRL:
        out |= 0x04
    if pygame_mod & pygame.KMOD_RCTRL:
        out |= 0x08
    if pygame_mod & pygame.KMOD_LALT:
        out |= 0x10
    if pygame_mod & pygame.KMOD_RALT:
        out |= 0x20
    return out
