"""
pyreborn - RC Client
Remote Control client for server administration.

RC (Remote Control) allows staff to administrate the server without being
in-game. RC clients can manage players, accounts, files, and server settings.
"""

import time
from typing import Optional, Callable, Dict, List

from .client import Client
from .protocol import ClientType
from .packets import (
    PacketID,
    parse_rc_chat,
    parse_rc_admin_message,
    parse_rc_server_flags,
    parse_rc_player_props,
    parse_rc_account_list,
    parse_rc_account_get,
    parse_rc_player_rights,
    parse_rc_player_comments,
    parse_rc_player_ban,
    parse_rc_filebrowser_dirlist,
    parse_rc_filebrowser_dir,
    parse_rc_filebrowser_message,
    parse_rc_server_options,
    parse_rc_folder_config,
    build_rc_chat,
    build_rc_admin_message,
    build_rc_priv_admin_message,
    build_rc_disconnect_player,
    build_rc_warp_player,
    build_rc_player_props_get,
    build_rc_player_props_get_by_name,
    build_rc_account_get,
    build_rc_account_add,
    build_rc_account_del,
    build_rc_player_ban_get,
    build_rc_player_ban_set,
    build_rc_player_rights_get,
    build_rc_player_comments_get,
    build_rc_player_comments_set,
    build_rc_server_flags_get,
    build_rc_server_options_get,
    build_rc_folder_config_get,
    build_rc_account_list_get,
    build_rc_update_levels,
    build_rc_filebrowser_start,
    build_rc_filebrowser_cd,
    build_rc_filebrowser_end,
    build_rc_filebrowser_download,
    build_rc_filebrowser_delete,
    build_rc_filebrowser_rename,
)


class RCClient(Client):
    """
    Remote Control client for server administration.

    Usage:
        rc = RCClient("localhost", 14900)
        rc.connect()
        rc.login("admin_account", "password")

        # RC Chat
        rc.rc_say("Hello other admins!")

        # Player management
        rc.kick_player(player_id)
        rc.warp_player(player_id, 30, 30, "level.nw")
        rc.ban_player("baduser", True, "Cheating")

        # Server management
        flags = rc.get_server_flags()
        accounts = rc.get_account_list()

        rc.disconnect()

    Note: RC login uses the same login packet as player login. The server
    determines RC access based on account staff rights and admin IP.
    """

    def __init__(self, host: str = "localhost", port: int = 14900, version: str = "2.22"):
        """
        Create a new RC client.

        Args:
            host: Server hostname or IP
            port: Server port (default 14900)
            version: Protocol version ("2.22" or "6.037")
        """
        super().__init__(host, port, version)

        # Set client type to RC2 for modern protocol login (2.22+)
        # TYPE_RC (1) is for old protocol, TYPE_RC2 (6) is for 2.22+ with ENCRYPT_GEN_5
        self._protocol.client_type_override = ClientType.TYPE_RC2

        # RC-specific state
        self._is_rc_mode = False

        # RC chat messages received
        self.rc_messages: List[str] = []

        # File browser state
        self.file_folders: List[str] = []
        self.file_current_folder: str = ""
        self.file_list: List[dict] = []
        self.file_browser_message: str = ""

        # Cached server data (populated on request)
        self._server_flags: List[str] = []
        self._server_options: Dict[str, str] = {}
        self._account_list: List[str] = []

        # RC-specific callbacks
        self.on_rc_chat: Optional[Callable[[str], None]] = None
        self.on_admin_message: Optional[Callable[[str, str], None]] = None
        self.on_filebrowser_update: Optional[Callable[[str, List[dict]], None]] = None

    # =========================================================================
    # RC Chat
    # =========================================================================

    def rc_say(self, message: str) -> bool:
        """
        Send a message to RC chat channel.

        Args:
            message: Message to send

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_chat(message)
        return self._protocol.send_packet(PacketID.PLI_RC_CHAT, data)

    def admin_message(self, message: str) -> bool:
        """
        Send an admin message to all players.

        Args:
            message: Message to broadcast

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_admin_message(message)
        return self._protocol.send_packet(PacketID.PLI_RC_ADMINMESSAGE, data)

    def private_admin_message(self, player_id: int, message: str) -> bool:
        """
        Send a private admin message to a specific player.

        Args:
            player_id: Target player ID
            message: Message to send

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_priv_admin_message(player_id, message)
        return self._protocol.send_packet(PacketID.PLI_RC_PRIVADMINMESSAGE, data)

    # =========================================================================
    # Player Management
    # =========================================================================

    def kick_player(self, player_id: int) -> bool:
        """
        Kick (disconnect) a player from the server.

        Args:
            player_id: Player ID to kick

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_disconnect_player(player_id)
        return self._protocol.send_packet(PacketID.PLI_RC_DISCONNECTPLAYER, data)

    def warp_player(self, player_id: int, x: float, y: float, level: str) -> bool:
        """
        Warp a player to a specific location.

        Args:
            player_id: Player ID to warp
            x: Destination X position
            y: Destination Y position
            level: Destination level name

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_warp_player(player_id, x, y, level)
        return self._protocol.send_packet(PacketID.PLI_RC_WARPPLAYER, data)

    def get_player_props_by_id(self, player_id: int) -> bool:
        """
        Request player properties by ID.
        Response arrives via PLO_RC_PLAYERPROPSGET packet.

        Args:
            player_id: Player ID to query

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_player_props_get(player_id)
        return self._protocol.send_packet(PacketID.PLI_RC_PLAYERPROPSGET2, data)

    def get_player_props_by_name(self, account: str) -> bool:
        """
        Request player properties by account name.
        Response arrives via PLO_RC_PLAYERPROPSGET packet.

        Args:
            account: Account name to query

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_player_props_get_by_name(account)
        return self._protocol.send_packet(PacketID.PLI_RC_PLAYERPROPSGET3, data)

    def get_player_rights(self, account: str) -> bool:
        """
        Request player rights/permissions.
        Response arrives via PLO_RC_PLAYERRIGHTSGET packet.

        Args:
            account: Account name to query

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_player_rights_get(account)
        return self._protocol.send_packet(PacketID.PLI_RC_PLAYERRIGHTSGET, data)

    def get_player_comments(self, account: str) -> bool:
        """
        Request player admin comments.
        Response arrives via PLO_RC_PLAYERCOMMENTSGET packet.

        Args:
            account: Account name to query

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_player_comments_get(account)
        return self._protocol.send_packet(PacketID.PLI_RC_PLAYERCOMMENTSGET, data)

    def set_player_comments(self, account: str, comments: str) -> bool:
        """
        Set player admin comments.

        Args:
            account: Account name
            comments: Comments text

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_player_comments_set(account, comments)
        return self._protocol.send_packet(PacketID.PLI_RC_PLAYERCOMMENTSSET, data)

    def get_ban_status(self, account: str) -> bool:
        """
        Request ban status for an account.
        Response arrives via PLO_RC_PLAYERBANGET packet.

        Args:
            account: Account name to query

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_player_ban_get(account)
        return self._protocol.send_packet(PacketID.PLI_RC_PLAYERBANGET, data)

    def ban_player(self, account: str, banned: bool = True, reason: str = "") -> bool:
        """
        Set ban status for an account.

        Args:
            account: Account name to ban/unban
            banned: True to ban, False to unban
            reason: Ban reason (optional)

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_player_ban_set(account, banned, reason)
        return self._protocol.send_packet(PacketID.PLI_RC_PLAYERBANSET, data)

    # =========================================================================
    # Account Management
    # =========================================================================

    def get_account_list(self) -> bool:
        """
        Request list of all accounts.
        Response arrives via PLO_RC_ACCOUNTLISTGET packet.

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_account_list_get()
        return self._protocol.send_packet(PacketID.PLI_RC_ACCOUNTLISTGET, data)

    def get_account(self, account: str) -> bool:
        """
        Request account details.
        Response arrives via PLO_RC_ACCOUNTGET packet.

        Args:
            account: Account name to query

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_account_get(account)
        return self._protocol.send_packet(PacketID.PLI_RC_ACCOUNTGET, data)

    def create_account(self, account: str, password: str, email: str = "") -> bool:
        """
        Create a new account.

        Args:
            account: New account name
            password: Account password
            email: Account email (optional)

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_account_add(account, password, email)
        return self._protocol.send_packet(PacketID.PLI_RC_ACCOUNTADD, data)

    def delete_account(self, account: str) -> bool:
        """
        Delete an account.

        Args:
            account: Account name to delete

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_account_del(account)
        return self._protocol.send_packet(PacketID.PLI_RC_ACCOUNTDEL, data)

    # =========================================================================
    # Server Management
    # =========================================================================

    def get_server_flags(self) -> bool:
        """
        Request server flags.
        Response arrives via PLO_RC_SERVERFLAGSGET packet.

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_server_flags_get()
        return self._protocol.send_packet(PacketID.PLI_RC_SERVERFLAGSGET, data)

    def get_server_options(self) -> bool:
        """
        Request server configuration options.
        Response arrives via PLO_RC_SERVEROPTIONSGET packet.

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_server_options_get()
        return self._protocol.send_packet(PacketID.PLI_RC_SERVEROPTIONSGET, data)

    def get_folder_config(self) -> bool:
        """
        Request folder configuration.
        Response arrives via PLO_RC_FOLDERCONFIGGET packet.

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_folder_config_get()
        return self._protocol.send_packet(PacketID.PLI_RC_FOLDERCONFIGGET, data)

    def update_levels(self) -> bool:
        """
        Request server to reload all levels.

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_update_levels()
        return self._protocol.send_packet(PacketID.PLI_RC_UPDATELEVELS, data)

    # =========================================================================
    # File Browser
    # =========================================================================

    def filebrowser_start(self) -> bool:
        """
        Start a file browser session.
        Response arrives via PLO_RC_FILEBROWSER_DIRLIST packet.

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_filebrowser_start()
        return self._protocol.send_packet(PacketID.PLI_RC_FILEBROWSER_START, data)

    def filebrowser_cd(self, folder: str) -> bool:
        """
        Change directory in file browser.
        Response arrives via PLO_RC_FILEBROWSER_DIR packet.

        Args:
            folder: Folder path to navigate to

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_filebrowser_cd(folder)
        return self._protocol.send_packet(PacketID.PLI_RC_FILEBROWSER_CD, data)

    def filebrowser_end(self) -> bool:
        """
        End file browser session.

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_filebrowser_end()
        return self._protocol.send_packet(PacketID.PLI_RC_FILEBROWSER_END, data)

    def filebrowser_download(self, filename: str) -> bool:
        """
        Request to download a file.

        Args:
            filename: File to download

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_filebrowser_download(filename)
        return self._protocol.send_packet(PacketID.PLI_RC_FILEBROWSER_DOWN, data)

    def filebrowser_delete(self, filename: str) -> bool:
        """
        Delete a file.

        Args:
            filename: File to delete

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_filebrowser_delete(filename)
        return self._protocol.send_packet(PacketID.PLI_RC_FILEBROWSER_DELETE, data)

    def filebrowser_rename(self, old_name: str, new_name: str) -> bool:
        """
        Rename a file.

        Args:
            old_name: Current filename
            new_name: New filename

        Returns:
            True if request sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        data = build_rc_filebrowser_rename(old_name, new_name)
        return self._protocol.send_packet(PacketID.PLI_RC_FILEBROWSER_RENAME, data)

    # =========================================================================
    # Packet Handling (Override parent)
    # =========================================================================

    def _handle_packet(self, packet_id: int, data: bytes):
        """Handle received packets, including RC-specific ones."""

        # RC Chat
        if packet_id == PacketID.PLO_RC_CHAT:
            message = parse_rc_chat(data)
            self.rc_messages.append(message)
            if self.on_rc_chat:
                self.on_rc_chat(message)
            # Mark as RC mode and authenticated on first RC chat received
            self._is_rc_mode = True
            if not self._authenticated:
                self._authenticated = True
            return

        # Admin Message
        if packet_id == PacketID.PLO_RC_ADMINMESSAGE:
            info = parse_rc_admin_message(data)
            if self.on_admin_message:
                self.on_admin_message(info.get('admin', ''), info.get('message', ''))
            return

        # Server Flags
        if packet_id == PacketID.PLO_RC_SERVERFLAGSGET:
            info = parse_rc_server_flags(data)
            self._server_flags = info.get('flags', [])
            return

        # Server Options
        if packet_id == PacketID.PLO_RC_SERVEROPTIONSGET:
            info = parse_rc_server_options(data)
            self._server_options = info.get('options', {})
            return

        # Account List
        if packet_id == PacketID.PLO_RC_ACCOUNTLISTGET:
            info = parse_rc_account_list(data)
            self._account_list = info.get('accounts', [])
            return

        # File Browser: Directory List
        if packet_id == PacketID.PLO_RC_FILEBROWSER_DIRLIST:
            info = parse_rc_filebrowser_dirlist(data)
            self.file_folders = info.get('folders', [])
            return

        # File Browser: Directory Contents
        if packet_id == PacketID.PLO_RC_FILEBROWSER_DIR:
            info = parse_rc_filebrowser_dir(data)
            self.file_current_folder = info.get('folder', '')
            self.file_list = info.get('files', [])
            if self.on_filebrowser_update:
                self.on_filebrowser_update(self.file_current_folder, self.file_list)
            return

        # File Browser: Message
        if packet_id == PacketID.PLO_RC_FILEBROWSER_MESSAGE:
            self.file_browser_message = parse_rc_filebrowser_message(data)
            return

        # Defer to parent for all other packets
        super()._handle_packet(packet_id, data)

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def is_rc(self) -> bool:
        """Check if connected as RC (based on receiving RC packets)."""
        return self._is_rc_mode

    @property
    def server_flags(self) -> List[str]:
        """Get cached server flags (call get_server_flags() first)."""
        return self._server_flags

    @property
    def server_options(self) -> Dict[str, str]:
        """Get cached server options (call get_server_options() first)."""
        return self._server_options

    @property
    def account_list(self) -> List[str]:
        """Get cached account list (call get_account_list() first)."""
        return self._account_list


# =============================================================================
# Convenience Function
# =============================================================================

def rc_connect(username: str, password: str,
               host: str = "localhost", port: int = 14900,
               version: str = "2.22") -> Optional[RCClient]:
    """
    Quick connect and login as RC.

    Args:
        username: Account name (must have RC rights)
        password: Account password
        host: Server hostname
        port: Server port
        version: Protocol version

    Returns:
        Connected and authenticated RCClient, or None if failed

    Usage:
        rc = rc_connect("admin", "pass")
        if rc:
            rc.rc_say("Admin online!")
            rc.disconnect()
    """
    rc = RCClient(host, port, version)

    if not rc.connect():
        return None

    if not rc.login(username, password):
        rc.disconnect()
        return None

    return rc
