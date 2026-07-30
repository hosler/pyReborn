"""Client AppearanceMixin methods."""

from __future__ import annotations

from reborn_protocol.props import PLAYER_PROPS, encode_value

from .packets import PacketID, build_chat, build_player_chat


class AppearanceMixin:
    def say(self, message: str) -> bool:
        """
        Send a chat message.

        Args:
            message: Message to send

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # Optimistic local echo: your own bubble/message shows immediately.
        # The server never relays your toall back to you (pid == m_id is skipped).
        self.player.chat = message
        data = build_chat(message)
        return self._protocol.send_packet(PacketID.PLI_TOALL, data)

    def send_level_chat(self, message: str) -> bool:
        """
        Send local level chat (shows above player's head).
        Uses PLPROP_CURCHAT (prop 12) via PLI_PLAYERPROPS.

        Args:
            message: Message to display

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # Optimistic local echo so our own bubble renders right away; the server
        # does not echo CURCHAT back to the setter.
        self.player.chat = message
        data = build_player_chat(message)
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)

    def _send_appearance_prop(self, prop_id: int, value) -> bool:
        """Send one appearance property through the normal player-props path."""
        if not self.connected or not self._authenticated:
            return False
        payload = bytes([prop_id + 32]) + encode_value(
            PLAYER_PROPS[prop_id], value, colors_len=self._colors_len)
        return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, payload)

    @staticmethod
    def _remember_appearance(**fields) -> None:
        try:
            from .prefs import Prefs
            Prefs.load().remember_appearance(**fields)
        except OSError:
            pass

    def send_head_image(self, head_image=None) -> bool:
        """Set and send PLPROP_HEADIMAGE (a preset int or custom filename)."""
        value = self.player.head_image if head_image is None else head_image
        sent = self._send_appearance_prop(11, value)
        if sent:
            self.player.head_image = (
                f"head{value}.png" if isinstance(value, int) else str(value))
            self._remember_appearance(head=self.player.head_image)
        return sent

    def send_body_image(self, body_image=None) -> bool:
        """Set and send PLPROP_BODYIMAGE."""
        value = self.player.body_image if body_image is None else str(body_image)
        sent = self._send_appearance_prop(35, value)
        if sent:
            self.player.body_image = value
            self._remember_appearance(body=value)
        return sent

    def send_colors(self, colors=None) -> bool:
        """Set and send PLPROP_COLORS using the negotiated server width."""
        value = list(self.player.colors if colors is None else colors)
        sent = self._send_appearance_prop(13, value)
        if sent:
            self.player.colors = value[:self._colors_len]
            self._remember_appearance(colors=self.player.colors)
        return sent

    def _apply_login_appearance(self, server_props: dict) -> None:
        """Restore saved look fields absent from the first server props packet."""
        if self._login_appearance_applied:
            return
        self._login_appearance_applied = True
        try:
            from .prefs import Prefs
            prefs = Prefs.load()
        except OSError:
            return

        server_values = {}
        if 'head_image' in server_props:
            server_values['head'] = self.player.head_image
        elif prefs.appearance_head is not None:
            self.send_head_image(prefs.appearance_head)
        if 'body_image' in server_props:
            server_values['body'] = self.player.body_image
        elif prefs.appearance_body is not None:
            self.send_body_image(prefs.appearance_body)
        if 'colors' in server_props:
            server_values['colors'] = self.player.colors
        elif prefs.appearance_colors is not None:
            self.send_colors(prefs.appearance_colors)
        if server_values:
            try:
                prefs.remember_appearance(**server_values)
            except OSError:
                pass
