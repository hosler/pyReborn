"""Client-side GS2 package component."""

from __future__ import annotations

from reborn_protocol.gs2 import GS2Object
from reborn_protocol.gs2 import VMCoroutineWait
from reborn_protocol.gs2 import to_num
from reborn_protocol.gs2 import to_str
from .registry import _FALL_THROUGH, _GS2_OBJ_METHODS, _GS2_STR_METHODS, _gs2_builtin, _gs2_sort_key
from .objects import _LevelObject

class HostObjmethodsMixin:

    @_gs2_builtin(_GS2_OBJ_METHODS, "getmappartfile", "findareanpcs",
                  "putbomb", "putbomb2")
    def _obj_level_methods(self, vm, name, args, obj):
        if not isinstance(obj, _LevelObject):
            return _FALL_THROUGH
        if name == "getmappartfile":
            return obj.map_part_file(args[0], args[1]) if len(args) >= 2 else ""
        if name == "findareanpcs":
            if len(args) < 4:
                return []
            x, y, w, h = map(to_num, args[:4])
            found = []
            for npc_id, npc in (getattr(self.rt2.client, "npcs", {}) or {}).items():
                nx = to_num(npc.get("world_x", npc.get("x", 0)))
                ny = to_num(npc.get("world_y", npc.get("y", 0)))
                if x <= nx < x + w and y <= ny < y + h:
                    owner = self.rt2.vms.get("npc", {}).get(npc_id)
                    if owner is not None:
                        found.append(owner.this)
            return found
        if len(args) < 3:
            return 0.0
        # putbomb2's fourth string selects bomb art in the reference. The
        # existing client placement path has no custom-art field; power/x/y
        # otherwise share putbomb's machinery.
        self.rt2._gs1_command("putbomb", list(args[:3]), vm)
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "showemoticonbykey", "showemoticon",
                  "hideemoticon", "scrollsign", "hidesign", "getnohit")
    def _obj_player_display(self, vm, name, args, obj):
        if obj is not self.rt2.player_object:
            return _FALL_THROUGH
        player = getattr(self.rt2.client, "player", None)
        game = getattr(self.rt2, "game_shell", None)
        if name == "getnohit":
            if int(getattr(self.rt2.client, "ghost_mode", 0) or 0) != 0:
                return 21.0
            if (not bool(to_num(obj.get("disableapsaint"))) and
                    to_num(getattr(player, "ap", 0)) > 99):
                return 22.0
            return 0.0
        if name in ("showemoticon", "showemoticonbykey"):
            if player is not None:
                player.emoticon = (int(to_num(args[0])) if name.endswith("bykey")
                                   else to_str(args[0])) if args else ""
            return 0.0
        if name == "hideemoticon":
            if player is not None:
                player.emoticon = ""
            return 0.0
        if name == "hidesign":
            if game is not None and hasattr(game, "_dismiss_dialogue"):
                game._dismiss_dialogue()
            return 0.0
        if game is not None and getattr(game, "dialogue_text", None) is not None:
            pager = getattr(game, "dialogue_pager", None)
            if pager is not None:
                pager.scroll(int(to_num(args[0])) if args else 0)
        return 0.0

    # -- _GS2_OBJ_METHODS: object methods with no type gate -----------------
    #
    # The TGraalVar ROOT methods live here rather than in _GS2_LIST_METHODS.
    # The reference registers them on TGraalVar, i.e. on EVERY object
    # (quattroplay/src/TGraalVarProperties.cpp:494 savelines, :548 settimer,
    # :557 sortascending, :566 sortdescending), so `this.savelines("f.txt", 0)`
    # and `this.settimer(1)` are valid spellings. An `isinstance(obj, list)`
    # gate here is not just narrow, it is LOAD-BEARING in the wrong direction:
    # the host is consulted before the VM, so a gate that does not match
    # walks on to the later stages and ends at 0.0 -- which is what these did
    # even after the VM widened its own root surface.
    # `add`/`size`/`clear`/`index` deliberately stay array-only in the VM:
    # those mirror compiled opcodes, not registered names.

    @_gs2_builtin(_GS2_STR_METHODS, "hasfunction")
    @_gs2_builtin(_GS2_OBJ_METHODS, "hasfunction")
    def _obj_hasfunction(self, vm, name, args, obj):
        if not args:
            return 0.0
        wanted = to_str(args[0])
        if isinstance(obj, str):
            owner = self.rt2.vms["weapon"].get(obj.lower())
            return 1.0 if owner is not None and owner.has_function(wanted) else 0.0
        if isinstance(obj, GS2Object):
            if obj.has(wanted):
                return 1.0
            if any(owner.has_public_function(wanted)
                   for owner in obj.script_vms):
                return 1.0
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "sortascending", "sortdescending")
    def _obj_sort_directed(self, vm, name, args, obj):
        if not isinstance(obj, list):
            # An object with no array cells has nothing to sort -- the same
            # answer the VM's root surface gives for addarray/sortbyvalue.
            return 0.0
        obj.sort(key=_gs2_sort_key, reverse=name == "sortdescending")
        return obj

    @_gs2_builtin(_GS2_OBJ_METHODS, "savelines")
    def _obj_savelines(self, vm, name, args, obj):
        # savelines(filename, appendflag): the second argument is the append
        # flag ("si"), which this client's server-scoped cache does not model
        # -- it always rewrites. A non-array object has no lines to write.
        if args and isinstance(obj, list):
            self.rt2.save_lines(to_str(args[0]), obj)
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "loadvars")
    def _obj_loadvars(self, vm, name, args, obj):
        # obj.loadvars(filename): populate the OBJECT's members from
        # `name=value` lines out of this client's server-scoped cache --
        # the object-target spelling of the bare loadvars above.
        # -Playerlist's options live behind exactly this
        # (`this.options.loadvars("scriptfiles/playerlistoptions.txt")`,
        # B/_Playerlist.gs2bc.gs2:882); a missing file leaves the object
        # untouched, which is the fresh-client state.
        if not isinstance(obj, GS2Object) or not args:
            return 0.0
        for line in self.rt2.load_lines(to_str(args[0])):
            key, sep, value = to_str(line).partition("=")
            if sep and key.strip():
                obj.set(key.strip(), value)
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "loadlines")
    def _obj_loadlines(self, vm, name, args, obj):
        # obj.loadlines(filename): the reference turns the target VAR into
        # an array of the file's lines (TGraalVar loadlines). When the
        # script pre-assigned an array we can refill it in place; a
        # vivified plain object cannot be re-typed from the host, so it
        # stays empty -- indistinguishable from the missing-file case,
        # which is the true state until savelines has written the group
        # files this weapon reads back.
        if isinstance(obj, list) and args:
            obj[:] = self.rt2.load_lines(to_str(args[0]))
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "settimer")
    def _obj_settimer(self, vm, name, args, obj):
        # Same timer store the bare form arms, keyed on the CALLING script:
        # the reference's timer lives on the TGraalVar it was called on, and
        # every live call site is a script arming its own `this`.
        return self._bi_settimer(vm, name, args, None)

    @_gs2_builtin(_GS2_OBJ_METHODS, "join")
    def _obj_join(self, vm, name, args, obj):
        if args:
            result = self.rt2.join_class(vm, to_str(args[0]))
            return result if isinstance(result, VMCoroutineWait) else 0.0
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "leave", "isinclass", "getcallstack")
    def _obj_class_ops(self, vm, name, args, obj):
        # The object-method spelling of the three bare forms. Every live
        # call site uses THIS one: Zelda's class:gui_builder built() ends
        # with `this.leave("gui_builder"); echo(... this.isinclass(
        # "gui_builder"))`, and g2k1's weaponParticleEditor dumps
        # `this.getCallStack()`.
        if vm is None:
            return _FALL_THROUGH
        rt2 = self.rt2
        if name == "getcallstack":
            return rt2.call_stack(vm)
        if name == "isinclass":
            return 1.0 if (args and rt2.is_in_class(vm, to_str(args[0]))) else 0.0
        if args:
            rt2.leave_class(vm, to_str(args[0]))
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "destroy")
    def _obj_destroy(self, vm, name, args, obj):
        if self.rt2.gui is None:
            return _FALL_THROUGH
        self.rt2.gui.destroy(obj)
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "scheduleevent", "cancelevents")
    def _obj_events(self, vm, name, args, obj):
        if vm is None:
            return _FALL_THROUGH
        rt2 = self.rt2
        if name == "scheduleevent" and len(args) >= 2:
            rt2.schedule_event(vm, to_num(args[0]), to_str(args[1]),
                               list(args[2:]))
        elif name == "cancelevents":
            rt2.cancel_events(vm, to_str(args[0]) if args else "")
        return 0.0
