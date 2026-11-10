"""GS1 message flag arguments and list search order."""

import pytest

from pyreborn import Client
from pyreborn.gs1_client import ClientGS1


def _run(script):
    client = Client('localhost', 14900)
    client.npcs[1] = {}
    runtime = ClientGS1(client)
    runtime.load_script('npc_1', script, npc_id=1)
    runtime.trigger_npc_event(1, 'created')
    return client.npcs[1], runtime


# Reference origin/beta4 server/src/scripting/gs1/GS1MessageCodes.cpp:138-143,
# 195-197: only the first argument of #I/#s defaults to client flag storage.
@pytest.mark.parametrize('index', ['i', 'i + 0'])
def test_list_message_index_is_an_ordinary_expression(index):
    npc, _ = _run(
        'i = 1; setstring client.i,2; '
        'setstring client.mylist,zero,one,two; '
        f'message #I(client.mylist,{index});')
    assert npc['message'] == 'one'


# Reference: GS1Visitor.cpp visitIdentifierValue (`!storage && expectingFlag`
# -> CLIENT storage) plus the d5b61a2d guard above. A prefixed name keeps its
# own scope; `this.mylist` is a different variable from `client.mylist`.
@pytest.mark.parametrize('expression,expected', [
    ('#I(mylist,i)', 'one'), ('#s(mylist)', 'zero,one,two'),
    ('#I(client.mylist,i)', 'one'), ('#s(client.mylist)', 'zero,one,two'),
    ('#I(this.mylist,i)', 'list'), ('#s(this.mylist)', 'wrong,list'),
])
def test_first_message_argument_defaults_to_client_flags(expression, expected):
    npc, _ = _run(
        'i = 1; setstring client.i,2; '
        'setstring this.mylist,wrong,list; '
        'setstring client.mylist,zero,one,two; '
        f'message {expression};')
    assert npc['message'] == expected


def test_lindexof_takes_item_before_list():
    # Reference origin/beta4 bin/docs/scripting-gs1-functions.md:579-594.
    _, runtime = _run(
        'setstring test,Testing; addstring test,More; addstring test,Stuff; '
        'this.found = lindexof(More,test); '
        'this.missing = lindexof(Hey,test); '
        'this.reversed = lindexof(test,More);')
    state = runtime._progs['npc_1']['scopes']['this']
    assert state['found'] == 1
    assert state['missing'] == -1
    assert state['reversed'] == -1
