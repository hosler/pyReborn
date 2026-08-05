"""Client-side GS2 package component."""

from __future__ import annotations

from typing import Any
from reborn_protocol.gs2 import GS2Object
from typing import Optional
from ..gs1_client import board_tile_read
from ..gs1_client import board_tile_write
from ..particles import emitter_for_record
from reborn_protocol.gs2 import to_bool
from reborn_protocol.gs2 import to_num
from reborn_protocol.gs2 import to_str
from reborn_protocol.coords import segment_at
from .helpers import _GANI_TRANSFORM_DEFAULTS
from .objects_player import _ThisObject, _guild_from_nick



#: GS2 NPC-script attribute name -> client npc-dict key. Same store the GS1
#: host writes (gs1_client.py NPC_ATTR/_CHARPROP_NPC) and render_entities.py
#: reads. v6 bytecode addresses these as BARE names (`y = 12.5;`,
#: `headimg = "...";`, `showimg(300, img, x, y)`) — the compiler scopes NPC
#: props implicitly, so the VM's this-object must claim them (has() below)
#: for both _lookup and _assign_name to bridge here instead of the shared
#: globals dict (which cross-contaminated every NPC in a level).
_NPC_THIS_ATTR = {
    "x": "x", "y": "y", "dir": "direction", "image": "image",
    "ani": "gani", "nick": "nickname", "chat": "message",
    "message": "message", "glovepower": "glove_power",
    "headimg": "head_image", "bodyimg": "body_image",
    "shieldimg": "shield_image", "swordimg": "sword_image",
    "horseimg": "horse_image",
    # Verified alias pairs: identical getter AND setter pointers in the same
    # table, so each is one slot under two names -- head/headimg
    # (quattroplay/src/TGaniObjectProperties.cpp:154 and :163), body/bodyimg
    # (:109, :118), shield/shieldimg and sword/swordimg
    # (src/TPlayerProperties.cpp:297/:306 and :333/:342). So `shield` on an
    # NPC is the shield IMAGE, never the shield power.
    "head": "head_image", "body": "body_image",
    "shield": "shield_image", "sword": "sword_image",
}

#: string-typed members an NPC `this` inherits from TServerPlayer that a
#: client-side NPC never has a value for. Answered as "" for the reason in
#: _PLAYER_EMPTY_STRINGS: unanswered would compare equal to every literal.
#: `account` src/TServerPlayerProperties.cpp:267, `communityname` :330,
#: `platform` :627.
_NPC_EMPTY_STRINGS = frozenset({"account", "communityname", "platform"})

#: the string-typed half of _NPC_THIS_ATTR (the rest -- x/y/dir/glovepower --
#: is numeric, where an unanswered read is already the right shape).
_NPC_STRING_ATTRS = frozenset({
    "image", "ani", "nick", "chat", "message", "headimg", "bodyimg",
    "shieldimg", "swordimg", "horseimg", "head", "body", "shield", "sword",
})


class _NpcColorsObject(GS2Object):
    """`colors[i]` / `color[i]` in an NPC script: indexed reads/writes bridge
    to the npc dict's color0..color4 slots (what _render_npc's character
    compositor reads). The VM's OP_ARRAY_ASSIGN/OP_ARRAY_INDEX call
    set/get with the stringified index when the target is a GS2Object."""

    __slots__ = ("_owner",)

    def __init__(self, owner: "_NpcThisObject"):
        super().__init__(name="npc.colors")
        self._owner = owner

    @staticmethod
    def _slot(key: str) -> Optional[str]:
        try:
            i = int(to_num(key))
        except (TypeError, ValueError):
            return None
        return f"color{i}" if 0 <= i <= 4 else None

    def get(self, key: str) -> Any:
        npc, slot = self._owner._npc(), self._slot(key)
        if npc is not None and slot:
            return npc.get(slot, "")
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        npc, slot = self._owner._npc(), self._slot(key)
        if npc is not None and slot:
            npc[slot] = to_str(value)
            return
        super().set(key, value)

    def has(self, key: str) -> bool:
        return self._slot(key) is not None or super().has(key)


class _NpcThisObject(_ThisObject):
    """An NPC script's `this`: NPC display/position attributes bridge to the
    live client npc dict (lazily resolved — bytecode can arrive before the
    NPC's props stream), everything else is plain member storage like
    _ThisObject. Bare names route here too via _lookup/_assign_name because
    has() claims the attribute names."""

    __slots__ = ("_colors", "_save")

    def __init__(self, rt2: "ClientGS2", vm_key: tuple, name: str = "this"):
        super().__init__(rt2, vm_key, name=name)
        self._colors = None
        # TServerNPC constructs `save` as a ten-element TNumberArrayVar.
        self._save = [0.0] * 10

    def _npc(self) -> Optional[dict]:
        cl = self._rt2.client
        if cl is None:
            return None
        npcs = getattr(cl, "npcs", {})
        key = self._vm_key[1]
        npc = npcs.get(key)
        if npc is None and isinstance(key, str):
            try:
                npc = npcs.get(int(key))
            except (TypeError, ValueError):
                npc = None
        return npc if isinstance(npc, dict) else None

    def _npc_id(self):
        """The client.npcs key this VM's record lives under — the same id
        render_entities iterates with, so speech-bubble entries keyed on it
        actually reach this NPC's draw."""
        cl = self._rt2.client
        if cl is None:
            return None
        npcs = getattr(cl, "npcs", {})
        key = self._vm_key[1]
        if key in npcs:
            return key
        if isinstance(key, str):
            try:
                ikey = int(key)
            except (TypeError, ValueError):
                return None
            if ikey in npcs:
                return ikey
        return None

    def has(self, key: str) -> bool:
        k = key.lower()
        if k in _NPC_THIS_ATTR or k in (
                "colors", "color", "actionplayer", "isblocking",
                "isblockingprojectiles", "npcsindex", "peltwithnpc",
                "peltwithbush", "peltwithsign", "peltwithvase",
                "peltwithstone", "peltwithblackstone", "save", "isweapon"):
            return True
        return super().has(key)

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in ("colors", "color"):
            if self._colors is None:
                self._colors = _NpcColorsObject(self)
            return self._colors
        if k == "isweapon":
            return 0.0
        if k == "save":
            return self._save
        npc = self._npc()
        if k == "actionplayer":
            # No action-player attribution on an untouched streamed NPC.
            # A locally dispatched action records the client id when present.
            action_id = (npc or {}).get("action_player_id", -1)
            if not isinstance(action_id, (int, float)) or action_id < 0:
                return -2.0
            player = getattr(self._rt2.client, "player", None)
            if action_id == getattr(player, "id", None):
                return 0.0
            players = list((getattr(self._rt2.client, "players", {}) or {}).keys())
            return float(players.index(action_id) + 1) if action_id in players else -1.0
        if k == "npcsindex":
            npc_id = self._npc_id()
            keys = list((getattr(self._rt2.client, "npcs", {}) or {}).keys())
            return float(keys.index(npc_id)) if npc_id in keys else -1.0
        if k == "isblocking":
            return 0.0 if (npc or {}).get("dontblock", False) else 1.0
        if k == "isblockingprojectiles":
            return 1.0 if (npc or {}).get("blocks_projectiles", True) else 0.0
        pelt_names = {
            "peltwithnpc": "npc", "peltwithbush": "bush",
            "peltwithsign": "sign", "peltwithvase": "vase",
            "peltwithstone": "stone", "peltwithblackstone": "blackstone",
        }
        if k in pelt_names:
            return 1.0 if (npc or {}).get("pelt_kind", "") == pelt_names[k] else 0.0
        attr = _NPC_THIS_ATTR.get(k)
        if attr is not None:
            npc = self._npc()
            if npc is not None and attr in npc:
                v = npc.get(attr)
                return v if isinstance(v, str) else to_num(v)
        if k == "guild":
            # RO, src/TServerPlayerProperties.cpp:384. Derived from the nick
            # exactly as TServerPlayer::setNick derives it -- see
            # _guild_from_nick.
            npc = self._npc()
            return _guild_from_nick((npc or {}).get("nickname", ""))
        if k in _NPC_EMPTY_STRINGS:
            return ""
        # Member storage still wins (bytecode can run before the NPC's props
        # stream, and set() parks writes there), so the string/transform
        # defaults only fill in a slot nobody has written.
        value = super().get(key)
        if value is None:
            if k in _NPC_STRING_ATTRS:
                return ""
            if k in _GANI_TRANSFORM_DEFAULTS:
                return _GANI_TRANSFORM_DEFAULTS[k]
        return value

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k == "isblocking":
            npc = self._npc()
            if npc is not None:
                npc["dontblock"] = not to_bool(value)
            return
        if k == "isblockingprojectiles":
            npc = self._npc()
            if npc is not None:
                npc["blocks_projectiles"] = to_bool(value)
            return
        if k in ("colors", "color") and isinstance(value, (list, tuple)):
            npc = self._npc()
            if npc is not None:
                for i, v in enumerate(value[:5]):
                    npc[f"color{i}"] = to_str(v)
                return
        attr = _NPC_THIS_ATTR.get(k)
        if attr is not None:
            npc = self._npc()
            if npc is not None:
                if attr in ("x", "y"):
                    # Keep the renderer's preferred world_x/world_y in step
                    # (client.py stamps them on every PLO_NPCPROPS, world ==
                    # local + segment offset), and snap the visual position —
                    # a script placement is not movement to lerp across.
                    new = to_num(value)
                    wkey = "world_" + attr
                    if wkey in npc and npc.get(wkey) is not None:
                        old = to_num(npc.get(attr, 0) or 0)
                        npc[wkey] = to_num(npc.get(wkey, 0) or 0) + (new - old)
                    npc[attr] = new
                    mark = getattr(self._rt2.client, "_mark_npc_pos_snap", None)
                    if mark is not None:
                        mark(npc)
                elif attr == "message":
                    # `this.chat = "Yes?"` is how a GS2 NPC speaks (bomber v6
                    # Isaac 10333, gani sen_grab). Storing it on the dict
                    # alone is silent — the renderer's bubble reads
                    # npc_chat_texts (render_entities._render_npc), fed for
                    # GS1 by the say/message command via rt.on_say (setup.py's
                    # on_say). Feed the same store from this write path.
                    # Numbers settle to text with GS2's rule (to_str), the
                    # same as any other GS2 value becoming display text.
                    text = value if isinstance(value, str) else to_str(value)
                    npc[attr] = text
                    say = getattr(self._rt2.gs1, "on_say", None)
                    npc_id = self._npc_id()
                    if say is not None and npc_id is not None:
                        say(npc_id, text)
                else:
                    npc[attr] = value if isinstance(value, str) else to_num(value)
                return
        super().set(key, value)


class _GaniThisObject(_ThisObject):
    """The hidden, per-wearer object used by a scripted animation."""

    __slots__ = ("_wearer_key",)

    def __init__(self, rt2: "ClientGS2", vm_key: tuple, wearer_key: tuple,
                 name: str = "this"):
        super().__init__(rt2, vm_key, name=name)
        self._wearer_key = wearer_key

    def mirror_wearer(self) -> None:
        wearer = self._rt2._gani_wearer_record(self._wearer_key)
        if wearer is None:
            return
        get = wearer.get if isinstance(wearer, dict) else (
            lambda key, default=None: getattr(wearer, key, default))
        x = get("world_x", None)
        y = get("world_y", None)
        super().set("x", get("x", 0.0) if x is None else x)
        super().set("y", get("y", 0.0) if y is None else y)
        super().set("dir", get("direction", get("dir", 0.0)))


class _LayerImage(GS2Object):
    """findimg(index) result: a LIVE view onto a showimg/showtext layer
    record in the GS1 layer store (the same dict the renderer draws).

    Property writes go straight through to the record — the reference
    client's findimg returns the engine's own image object, so scripts
    animate layers by assigning `findimg(i).rotation`, update captions via
    `.text`, toggle `.visible`, move layers with `.x/.y`, etc. A detached
    copy (the previous implementation) silently dropped all of those.

    The record stores `rotation` and `visible` for the renderer. `layer` maps to
    the classic vis band (changeimgvis).
    """

    #: era new-GS1 with-scope member bridge (see gs1_client.get_builtin)
    gs1_with_members = True

    __slots__ = ("_rec",)

    _NUM_KEYS = frozenset(("x", "y", "zoom", "rotation", "mode"))
    _STR_KEYS = frozenset(("image", "font", "style"))

    #: every string-typed TShowImg property (src/TShowImgProperties.cpp:144,
    #: :171, :198, :207, :216, :225, :234, :270, :360, :387, :477, :531,
    #: :558). A layer property nobody has written must still read as a STRING
    #: -- see _PLAYER_EMPTY_STRINGS for what an unanswered one does.
    _SHOWIMG_STRINGS = frozenset((
        "ani", "image", "font", "shadowoffset", "shadowcolor", "style",
        "text", "code", "position", "rotationcenter", "attachoffset",
        "movementvector", "sound",
    ))

    #: names get() COMPUTES rather than reads out of the record/member dict.
    #: has() must claim the whole readable surface (these + the string/num
    #: property vocabulary + whatever the record holds) because the VM's
    #: with-stack resolution is has()-gated (vm._lookup/_assign_name):
    #: an unclaimed name inside `with (findimg(i)) { ... }` silently reads
    #: None and WRITES to VM globals -- `emitter` was invisible and the
    #: era corpus' `with (findimg(200)) { emitter... }` pattern configured
    #: nothing. Same idiom as the other host bridge objects (_NpcColorsObject
    #: etc.).
    _COMPUTED_KEYS = frozenset(("visible", "layer", "emitter", "textshadow"))

    def __init__(self, index: int, rec: dict):
        super().__init__(name=f"image:{index}")
        self._rec = rec

    def has(self, key: str) -> bool:
        k = key.lower()
        return (k in self._COMPUTED_KEYS or k in self._NUM_KEYS
                or k in self._SHOWIMG_STRINGS or k in self._rec
                or super().has(key))

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "visible":
            return 1.0 if self._rec.get("visible", True) else 0.0
        if k == "layer":
            return float(self._rec.get("vis", 4))
        if k == "emitter":
            # read-only object prop, lazy-created + identity-stable
            # (TShowImg::getParticleEmitter, quattroplay/src/TShowImg
            # .cpp:180-185)
            return emitter_for_record(self._rec)
        v = self._rec.get(k)
        if v is None:
            v = super().get(k)
        if v is None and k in self._SHOWIMG_STRINGS:
            return ""
        return v

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k == "emitter":
            # nullptr setter in the reference property table
            # (TShowImgProperties.cpp:495-498)
            return
        if k == "visible":
            self._rec["visible"] = to_bool(value)
        elif k == "layer":
            self._rec["vis"] = int(to_num(value))
            self._rec["vis_set"] = True
        elif k in self._NUM_KEYS:
            self._rec[k] = to_num(value)
        elif k in self._STR_KEYS:
            self._rec[k] = to_str(value)
        elif k == "text":
            self._rec["text"] = to_str(value)
            self._rec["text_is"] = True
        elif k == "textshadow":
            self._rec["textshadow"] = to_bool(value)
        else:
            # unknown property: keep it on the record so a renderer that
            # learns the key later just works (and reads round-trip)
            self._rec[k] = value


def layer_image_get(table: dict, index: int, owner=None):
    """Shared findimg(index) resolver for BOTH engines: the identity-cached
    live _LayerImage over the layer record, CREATING an empty record on a
    miss.  The decompiled NPC binding answers null for an unknown index
    (TShowImgList::getByImgIndex), but live-server particle content
    configures emitters on virgin indices as a matter of course --
    era_partyhouse.nw:495 even does `hideimg(200). With (findimg(200))
    {...}` -- so on the shipping client the pattern must materialize a
    layer. An empty record draws nothing until a script gives it content.
    `owner` (the running NPC's dict, when there is one) is stashed for the
    renderer's attachtoowner anchoring."""
    record = table.get(index)
    if record is None:
        record = table[index] = {}
        if owner is not None:
            record["_owner"] = owner
    obj = record.get("_findimg")
    # identity check: showtext REPLACES the rec dict for an index, so a
    # cached wrapper can point at a dead dict
    if not isinstance(obj, _LayerImage) or obj._rec is not record:
        obj = record["_findimg"] = _LayerImage(index, record)
    return obj


class _LevelObject(GS2Object):
    """`level.` bridged onto the client's current level.

    Its chain is TServerLevel -> TGraalVar: six own properties
    (quattroplay/src/TServerLevelProperties.cpp:60-115) plus TGraalVar's
    eight (src/TGraalVarProperties.cpp:625-698). All fourteen used to read
    0.0, `name` included -- and `level.name == "somelevel.nw"` is a common
    script idiom, so it was true in EVERY level."""

    __slots__ = ("_rt2",)

    def __init__(self, rt2: "ClientGS2"):
        super().__init__(name="level")
        self._rt2 = rt2

    @property
    def name(self) -> str:
        # Shadows GS2Object's `name` slot on purpose: gs2_compare's
        # object-vs-string row reads the object's name field, so a bare
        # `level == "x.nw"` has to see the level filename rather than the
        # literal string "level".
        return self._name()

    @name.setter
    def name(self, value) -> None:
        # no-op for the same reason set("name") is -- see below
        pass

    def _name(self) -> str:
        # TServerLevel hands TFiles::lowerCaseFilename(levelName) to the
        # TGraalVar base (src/TServerLevel.cpp:352-354), so the script-visible
        # name is the LOWER-CASED level filename.
        client = self._rt2.client
        return to_str(getattr(client, "_current_level_name", "") or "").lower()

    def _span(self, segments_attr: str) -> float:
        # 64 for a plain level; on a gmap the MAP's segment count << 6
        # (propfun_serverlevel_width_r / _height_r,
        # src/TServerLevelProperties.cpp:43-53 and :6-16).
        client = self._rt2.client
        segments = int(getattr(client, segments_attr, 0) or 0) if client else 0
        return float(segments << 6) if segments > 0 else 64.0

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "name":
            return self._name()
        if k == "width":
            return self._span("gmap_width")
        if k == "height":
            return self._span("gmap_height")
        if k == "preloadleveldefaulttile":
            value = super().get(k)
            return 0.0 if value is None else to_num(value)
        if k in ("isnopkzone", "nopkzone"):
            value = super().get("isnopkzone")
            return 0.0 if value is None else (1.0 if to_bool(value) else 0.0)
        if k == "issparringzone":
            # The level constructor clears this flag and no handled packet
            # supplies it to this client.
            return 0.0
        if k == "tilelayercount":
            # TServerLevel's m_tileLayers array size. PLO_BOARDLAYER ids are
            # sparse here, so report the highest occupied one; a level with
            # only the base board has exactly one layer.
            layers = getattr(self._rt2.client, "board_layers", None) or {}
            stored = super().get(k)
            if stored is not None:
                return to_num(stored)
            return float(max([0] + [int(i) for i in layers]) + 1)
        if k in ("joinedclasses", "scripterrors"):
            # TGraalVar object-typed lists (:654, :672). Nothing joins or
            # errors on the level object here; an empty array is what a
            # script iterating one expects.
            return []
        value = super().get(key)
        if value is None:
            # The remaining TGraalVar entries -- initialized (:636),
            # ispaused (:645), maxlooplimit (:663),
            # scriptlogmissingfunctions (:681), timeout (:690) -- and
            # TServerLevel's isnopkzone / nopkzone / issparringzone
            # (:71, :89, :80) are all numeric or boolean, where 0.0 is both
            # the right shape and the right value for a client-side level.
            return 0.0
        return value

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k == "name":
            # propfun_graalvar_name_w (src/TGraalVarProperties.cpp:154-161)
            # assigns only while the object is still unnamed AND unlinked; a
            # live level is neither, so the write is a no-op there too.
            return
        if k in ("isnopkzone", "nopkzone"):
            super().set("isnopkzone", 1.0 if to_bool(value) else 0.0)
            return
        if k == "issparringzone":
            return
        super().set(key, value)

    def map_part_file(self, x: Any, y: Any) -> str:
        client = self._rt2.client
        if client is None:
            return ""
        cell = segment_at(to_num(x), to_num(y))
        return to_str((getattr(client, "gmap_grid", {}) or {}).get(cell, ""))


class _BoardTilesColumn(list):
    """One column of the live `tiles[]` view (see ClientGS2.tiles_view).

    A real list subclass so every VM op that gates on isinstance(list)
    (OP_ARRAY / OP_ARRAY_ASSIGN / OP_ARRAY_MULTIDIM*) accepts it, but the
    element storage is the CLIENT BOARD: reads and writes route through the
    gmap-aware helpers in gs1_client, so world coords hit the owning
    segment's board and a write patches the real board (collision) plus the
    renderer's cached segment surface -- not a detached snapshot. The base
    list stays empty. __len__ supplies the world height so the VM's bounds
    checks and its extend-on-grow path stay in-range without materializing
    placeholder rows."""

    __slots__ = ("_rt2", "_x", "_h")

    def __init__(self, rt2: "ClientGS2", x: int, height: int):
        super().__init__()
        self._rt2 = rt2
        self._x = x
        self._h = height

    def __len__(self) -> int:
        return self._h

    def __bool__(self) -> bool:
        return self._h > 0

    def __iter__(self):
        return (self[i] for i in range(self._h))

    def __getitem__(self, y):
        if isinstance(y, slice):
            return [self[i] for i in range(*y.indices(self._h))]
        v = board_tile_read(self._rt2.client, self._x, y)
        return 0.0 if v is None else v

    def __setitem__(self, y, value):
        if not isinstance(y, slice):
            board_tile_write(self._rt2.client, self._x, y, to_num(value))
