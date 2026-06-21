"""
pyreborn - NC Client
NPC Control client for server-side NPC / weapon / class administration.

NC (NPC Control) is the connection the npc-server and npc editors use to manage
database NPCs, server weapons, GUI/weapon scripts ("classes") and level lists.

Unlike the game/RC connections (ENCRYPT_GEN_5), NC negotiates ENCRYPT_GEN_2:
zlib-framed bundles with no per-packet encryption and no encryption-key byte in
the login packet. See Protocol.use_gen2(). The server side lives in
GServer-v2 server/src/player/PlayerNC.cpp + packets/PlayerNCPackets.cpp.

Note: the NPC/class management replies (PLO_NC_NPCADD/NPCSCRIPT/CLASSGET/...) are
only emitted when the server has a running npc-server (V8/GS2). Without one, the
weapon-list, weapon-get, level-list and local-npcs queries still work.
"""

import time
from typing import Optional, Callable, Dict, List

from .client import Client
from .protocol import ClientType
from .packets import (
    PacketID,
    parse_nc_weapon_list,
    parse_nc_level_list,
    parse_nc_level_dump,
    parse_nc_weapon_get,
    parse_nc_npc_attributes,
    parse_nc_npc_add,
    parse_nc_npc_delete,
    parse_nc_npc_script,
    parse_nc_npc_flags,
    parse_nc_class_get,
    parse_nc_class_add,
    parse_nc_class_delete,
    parse_weapon_add,
    parse_rc_chat,
    build_nc_npcget,
    build_nc_npcdelete,
    build_nc_npcreset,
    build_nc_npcscriptget,
    build_nc_npcwarp,
    build_nc_npcflagsget,
    build_nc_npcscriptset,
    build_nc_npcflagsset,
    build_nc_npcadd,
    build_nc_classedit,
    build_nc_classadd,
    build_nc_localnpcsget,
    build_nc_weaponlistget,
    build_nc_weaponget,
    build_nc_weaponadd,
    build_nc_weapondelete,
    build_nc_classdelete,
    build_nc_levellistget,
)


class NCClient(Client):
    """
    NPC Control client.

    Usage:
        nc = NCClient("localhost", 14900)
        nc.connect()
        nc.login("npcadmin", "password")

        weapons = nc.get_weapon_list()      # PLO_NC_WEAPONLISTGET
        levels = nc.get_level_list()        # PLO_NC_LEVELLIST
        nc.get_weapon("-gr_movement")       # PLO_NC_WEAPONGET / NPCWEAPONADD
        nc.add_weapon("qa_w", "img.png", "//code")

        nc.disconnect()
    """

    def __init__(self, host: str = "localhost", port: int = 14900,
                 version: str = "6.037"):
        super().__init__(host, port, version)

        # NC uses PLTYPE_NC + ENCRYPT_GEN_2 framing.
        self._protocol.client_type_override = ClientType.TYPE_NC
        self._protocol.use_gen2()

        # PLO ids this class adds a dispatch branch for (kept in sync with
        # _handle_packet below) so the coverage harness counts them handled.
        self._handled_plo_ids |= {
            PacketID.PLO_NC_WEAPONLISTGET, PacketID.PLO_NC_LEVELLIST,
            PacketID.PLO_NC_LEVELDUMP, PacketID.PLO_NC_WEAPONGET,
            PacketID.PLO_NPCWEAPONADD, PacketID.PLO_RC_CHAT,
            PacketID.PLO_NC_NPCATTRIBUTES, PacketID.PLO_NC_NPCADD,
            PacketID.PLO_NC_NPCDELETE, PacketID.PLO_NC_NPCSCRIPT,
            PacketID.PLO_NC_NPCFLAGS, PacketID.PLO_NC_CLASSGET,
            PacketID.PLO_NC_CLASSADD, PacketID.PLO_NC_CLASSDELETE,
        }

        self._is_nc_mode = False

        # Cached query results (populated on response).
        self._weapon_list: List[str] = []
        self._level_list: List[str] = []
        self._last_weapon: Dict = {}
        self._last_level_dump: str = ""
        # NPC/class state (populated when a npc-server is running).
        self.npcs: Dict[int, Dict] = {}          # id -> {name,type,level}
        self.classes: List[str] = []             # known class names
        self._last_npc_attributes: List[str] = []
        self._last_npc_script: Dict = {}
        self._last_npc_flags: Dict = {}
        self._last_class: Dict = {}
        # RC-style status/log lines the server sends NCs via PLO_RC_CHAT.
        self.nc_messages: List[str] = []

        # Callbacks.
        self.on_weapon_list: Optional[Callable[[List[str]], None]] = None
        self.on_level_list: Optional[Callable[[List[str]], None]] = None
        self.on_weapon: Optional[Callable[[Dict], None]] = None
        self.on_nc_message: Optional[Callable[[str], None]] = None

    # =========================================================================
    # NPC management (require a running npc-server to elicit a reply)
    # =========================================================================

    def ping_npcs(self) -> bool:
        """PLI_NC_NPCGET with empty body - the npc-server keepalive/poll."""
        return self._send(PacketID.PLI_NC_NPCGET, build_nc_npcget())

    def get_npc(self, npc_id: int) -> bool:
        """Request a database NPC's attribute dump (-> PLO_NC_NPCATTRIBUTES)."""
        return self._send(PacketID.PLI_NC_NPCGET, build_nc_npcget(npc_id))

    def delete_npc(self, npc_id: int) -> bool:
        return self._send(PacketID.PLI_NC_NPCDELETE, build_nc_npcdelete(npc_id))

    def reset_npc(self, npc_id: int) -> bool:
        return self._send(PacketID.PLI_NC_NPCRESET, build_nc_npcreset(npc_id))

    def get_npc_script(self, npc_id: int) -> bool:
        return self._send(PacketID.PLI_NC_NPCSCRIPTGET,
                          build_nc_npcscriptget(npc_id))

    def warp_npc(self, npc_id: int, x: float, y: float, level: str) -> bool:
        return self._send(PacketID.PLI_NC_NPCWARP,
                          build_nc_npcwarp(npc_id, x, y, level))

    def get_npc_flags(self, npc_id: int) -> bool:
        return self._send(PacketID.PLI_NC_NPCFLAGSGET,
                          build_nc_npcflagsget(npc_id))

    def set_npc_script(self, npc_id: int, script: str) -> bool:
        return self._send(PacketID.PLI_NC_NPCSCRIPTSET,
                          build_nc_npcscriptset(npc_id, script))

    def set_npc_flags(self, npc_id: int, flags: str) -> bool:
        return self._send(PacketID.PLI_NC_NPCFLAGSSET,
                          build_nc_npcflagsset(npc_id, flags))

    def add_npc(self, name: str, npc_id: int, npc_type: str, scripter: str,
                level: str, x: float, y: float) -> bool:
        """PLI_NC_NPCADD: CSV info name,id,type,scripter,level,x,y."""
        info = ",".join([name, str(npc_id), npc_type, scripter, level,
                         str(x), str(y)])
        return self._send(PacketID.PLI_NC_NPCADD, build_nc_npcadd(info))

    def get_local_npcs(self, level: str) -> bool:
        """Request the variable dump for a level's NPCs (-> PLO_NC_LEVELDUMP)."""
        return self._send(PacketID.PLI_NC_LOCALNPCSGET,
                          build_nc_localnpcsget(level))

    # =========================================================================
    # Class (weapon/GUI script) management
    # =========================================================================

    def edit_class(self, class_name: str) -> bool:
        """Request a class's script (-> PLO_NC_CLASSGET)."""
        return self._send(PacketID.PLI_NC_CLASSEDIT,
                          build_nc_classedit(class_name))

    def add_class(self, class_name: str, script: str) -> bool:
        return self._send(PacketID.PLI_NC_CLASSADD,
                          build_nc_classadd(class_name, script))

    def delete_class(self, class_name: str) -> bool:
        return self._send(PacketID.PLI_NC_CLASSDELETE,
                          build_nc_classdelete(class_name))

    # =========================================================================
    # Weapon management
    # =========================================================================

    def get_weapon_list(self) -> bool:
        """Request the server weapon list (-> PLO_NC_WEAPONLISTGET)."""
        return self._send(PacketID.PLI_NC_WEAPONLISTGET, build_nc_weaponlistget())

    def get_weapon(self, weapon: str) -> bool:
        """Request a weapon's image+script (-> PLO_NC_WEAPONGET / NPCWEAPONADD)."""
        return self._send(PacketID.PLI_NC_WEAPONGET, build_nc_weaponget(weapon))

    def add_weapon(self, weapon: str, image: str, code: str) -> bool:
        """Add/update a server weapon. Replies with an updated weapon list."""
        return self._send(PacketID.PLI_NC_WEAPONADD,
                          build_nc_weaponadd(weapon, image, code))

    def delete_weapon(self, weapon: str) -> bool:
        return self._send(PacketID.PLI_NC_WEAPONDELETE,
                          build_nc_weapondelete(weapon))

    # =========================================================================
    # Level list
    # =========================================================================

    def get_level_list(self) -> bool:
        """Request the server level list (-> PLO_NC_LEVELLIST)."""
        return self._send(PacketID.PLI_NC_LEVELLISTGET, build_nc_levellistget())

    # =========================================================================
    # Internals
    # =========================================================================

    def _send(self, packet_id: int, data: bytes) -> bool:
        if not self.connected or not self._authenticated:
            return False
        return self._protocol.send_packet(packet_id, data)

    def _handle_packet(self, packet_id: int, data: bytes):
        """Handle NC-specific replies; defer the rest to the base client."""

        # The first NC packet from the server is PLO_SIGNATURE; NC logins never
        # get PLO_PLAYERPROPS, so latch authentication here.
        if not self._authenticated:
            self._is_nc_mode = True
            self._authenticated = True

        if packet_id == PacketID.PLO_NC_WEAPONLISTGET:
            self._weapon_list = parse_nc_weapon_list(data)
            if self.on_weapon_list:
                self.on_weapon_list(self._weapon_list)
            return

        if packet_id == PacketID.PLO_NC_LEVELLIST:
            self._level_list = parse_nc_level_list(data)
            if self.on_level_list:
                self.on_level_list(self._level_list)
            return

        if packet_id == PacketID.PLO_NC_LEVELDUMP:
            self._last_level_dump = parse_nc_level_dump(data)
            return

        if packet_id == PacketID.PLO_NC_WEAPONGET:
            self._last_weapon = parse_nc_weapon_get(data)
            if self.on_weapon:
                self.on_weapon(self._last_weapon)
            return

        # Older NC protocol delivers a requested weapon as PLO_NPCWEAPONADD.
        if packet_id == PacketID.PLO_NPCWEAPONADD:
            weapon = parse_weapon_add(data)
            if weapon and weapon.get('name'):
                self._last_weapon = weapon
                if self.on_weapon:
                    self.on_weapon(weapon)
            return

        # Status / log lines (NPC added, weapon updated, errors, "New NC:" ...).
        if packet_id == PacketID.PLO_RC_CHAT:
            msg = parse_rc_chat(data)
            self.nc_messages.append(msg)
            if self.on_nc_message:
                self.on_nc_message(msg)
            return

        # --- NPC / class management replies (npc-server only) -------------
        if packet_id == PacketID.PLO_NC_NPCATTRIBUTES:
            self._last_npc_attributes = parse_nc_npc_attributes(data)
            return

        if packet_id == PacketID.PLO_NC_NPCADD:
            npc = parse_nc_npc_add(data)
            self.npcs[npc['id']] = npc
            return

        if packet_id == PacketID.PLO_NC_NPCDELETE:
            self.npcs.pop(parse_nc_npc_delete(data), None)
            return

        if packet_id == PacketID.PLO_NC_NPCSCRIPT:
            self._last_npc_script = parse_nc_npc_script(data)
            return

        if packet_id == PacketID.PLO_NC_NPCFLAGS:
            self._last_npc_flags = parse_nc_npc_flags(data)
            return

        if packet_id == PacketID.PLO_NC_CLASSGET:
            self._last_class = parse_nc_class_get(data)
            return

        if packet_id == PacketID.PLO_NC_CLASSADD:
            name = parse_nc_class_add(data)
            if name and name not in self.classes:
                self.classes.append(name)
            return

        if packet_id == PacketID.PLO_NC_CLASSDELETE:
            name = parse_nc_class_delete(data)
            if name in self.classes:
                self.classes.remove(name)
            return

        super()._handle_packet(packet_id, data)

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def is_nc(self) -> bool:
        return self._is_nc_mode

    @property
    def weapon_list(self) -> List[str]:
        return self._weapon_list

    @property
    def level_list(self) -> List[str]:
        return self._level_list

    @property
    def last_weapon(self) -> Dict:
        return self._last_weapon

    @property
    def last_level_dump(self) -> str:
        return self._last_level_dump

    @property
    def last_npc_attributes(self) -> List[str]:
        return self._last_npc_attributes

    @property
    def last_npc_script(self) -> Dict:
        return self._last_npc_script

    @property
    def last_npc_flags(self) -> Dict:
        return self._last_npc_flags

    @property
    def last_class(self) -> Dict:
        return self._last_class


def nc_connect(username: str, password: str,
               host: str = "localhost", port: int = 14900,
               version: str = "6.037") -> Optional[NCClient]:
    """Quick connect + login as an NC client. Returns None on failure."""
    nc = NCClient(host, port, version)
    if not nc.connect():
        return None
    if not nc.login(username, password):
        nc.disconnect()
        return None
    return nc
