"""Level-file routing, including directed doors and ordinary GMAP seams."""

import pytest

from game_tester.world_graph import WorldGraph


@pytest.fixture
def world_graph(tmp_path):
    levels = tmp_path / 'levels'
    levels.mkdir()
    (levels / 'Start.nw').write_text(
        'GLEVNW01\nLINK HALL.nw 10 5 3 1 playerx 20\n'
        'LINK broken.nw bad 1 2 3 4 5\n')
    (levels / 'hall.nw').write_text('GLEVNW01\n')
    (levels / 'end.nw').write_text('LINK start.nw 1 2 3 4 5 playery\n')
    (tmp_path / 'map.gmap').write_text(
        'GRMAP001\nWIDTH 2\nHEIGHT 1\nLEVELNAMES\n'
        '"hall.nw","end.nw",\nLEVELNAMES END\n')
    return WorldGraph.from_world_dir(tmp_path)


def test_recursive_link_parsing_skips_malformed_and_preserves_coordinates(world_graph):
    links = world_graph.neighbours('START.NW')
    assert len(links) == 1
    hop = links[0]
    assert hop.source_level == 'Start.nw' and hop.dest_level == 'hall.nw'
    assert (hop.x, hop.y, hop.width, hop.height) == (10, 5, 3, 1)
    assert (hop.dest_x, hop.dest_y, hop.seam) == ('playerx', 20, False)


def test_bfs_chains_door_and_bidirectional_seam(world_graph):
    route = world_graph.route('start.NW', 'END.nw')
    assert [hop.dest_level for hop in route] == ['hall.nw', 'end.nw']
    assert [hop.seam for hop in route] == [False, True]
    assert world_graph.route('end.nw', 'hall.nw')[0].seam
    assert world_graph.route('START.NW', 'start.nw') == []
    assert world_graph.route('start.nw', 'missing.nw') is None
    assert world_graph.route('missing.nw', 'start.nw') is None
    assert world_graph.neighbours('missing.nw') == []


def test_observed_links_merge_dedupe_and_bfs_prefers_direct_route(world_graph):
    link = dict(x=9, y=8, width=2, height=1, dest_level='END.NW',
                dest_x=30, dest_y='playery')
    world_graph.add_observed('Start.nw', [link, link])
    assert len(world_graph.neighbours('start.nw')) == 2
    route = world_graph.route('start.nw', 'end.nw')
    assert len(route) == 1 and not route[0].seam
    assert (route[0].dest_x, route[0].dest_y) == (30, 'playery')
    link['x'] = 42
    assert route[0].x == 9


@pytest.mark.parametrize('change', [dict(width=0), dict(x='nan'), dict(dest_x='oops'),
                                    dict(dest_level=''), dict(dest_y='inf')])
def test_bad_observations_are_ignored(change):
    graph = WorldGraph()
    link = dict(x=1, y=1, width=1, height=1, dest_level='b.nw', dest_x=1, dest_y=1)
    graph.add_observed('a.nw', [dict(link, **change), {}])
    assert graph.neighbours('a.nw') == []


def test_bfs_handles_directed_cycles():
    graph = WorldGraph()
    for src, dest in [('a', 'b'), ('b', 'a'), ('b', 'c')]:
        graph.add_observed(src, [dict(x=1, y=1, width=1, height=1,
                                      dest_level=dest, dest_x=0, dest_y=0)])
    assert len(graph.route('a', 'c')) == 2
    assert graph.route('c', 'a') is None
