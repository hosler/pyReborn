"""PLO_BIGMAP (171) / PLO_MINIMAP (172): image and level list in either order.

Wire: `GChar id` + raw `a,b,c,d` (GServer-v2 origin/beta4
PlayerClient.cpp:499-512; forwarded verbatim). Shipped serveroptions use
`maptext,image,x,y`; GS1 setmap calls use `image,levelsfile,x,y`.
"""

import pytest

from pyreborn import Client
from pyreborn.packets import PacketID, parse_bigmap, parse_minimap

IMAGE_FIRST = {'image': 'map2.png', 'levels_file': 'minimap.txt',
               'x': 4.25, 'y': 9.25}


@pytest.mark.parametrize('parser', [parse_bigmap, parse_minimap])
@pytest.mark.parametrize('text', [b'minimap.txt,map2.png,4.25,9.25',
                                  b'map2.png,minimap.txt,4.25,9.25',
                                  b' minimap.txt , MAP2.PNG ,4.25,9.25'])
def test_either_order(parser, text):
    parsed = parser(text)
    assert parsed['levels_file'] == 'minimap.txt'
    assert parsed['image'].lower() == 'map2.png'
    assert (parsed['x'], parsed['y']) == (4.25, 9.25)


def test_oracle_vectors():
    assert parse_bigmap(b'bigmap.txt,bigmap.png,0,0') == {
        'image': 'bigmap.png', 'levels_file': 'bigmap.txt', 'x': 0.0, 'y': 0.0}
    assert parse_minimap(b'minimap.txt,map2.png,4.25,9.25') == IMAGE_FIRST


@pytest.mark.parametrize('ext', ['png', 'gif', 'bmp', 'jpg'])
def test_image_extensions(ext):
    parsed = parse_bigmap(('w.txt,pic.%s,1,2' % ext).encode())
    assert parsed['image'] == 'pic.' + ext and parsed['levels_file'] == 'w.txt'


def test_unknown_image_extension_still_picks_the_non_text_token():
    parsed = parse_bigmap(b'w.txt,pic.xyz,1,2')
    assert parsed['image'] == 'pic.xyz' and parsed['levels_file'] == 'w.txt'


def test_bad_numbers_and_short_packets_do_not_raise():
    assert parse_bigmap(b'a.png,b.txt')['x'] == 0.0
    assert parse_bigmap(b'a.png,b.txt,q,r')['y'] == 0.0


def test_login_order_keeps_both_configurations():
    """Reference login order is BIGMAP then MINIMAP (PlayerClient.cpp:489-516):
    the second packet must not replace the first."""
    client = Client('localhost', 14900)
    client._handle_packet(PacketID.PLO_BIGMAP, b'bigmap.txt,bigmap.png,0,0')
    client._handle_packet(PacketID.PLO_MINIMAP, b'minimap.txt,map2.png,4.25,9.25')
    assert client.bigmap_info['image'] == 'bigmap.png'
    assert client.minimap_info == IMAGE_FIRST
