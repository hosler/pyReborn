"""Phase 4: size-capped caches evict the least recent entry, not everything.

Mutations (each fails the named assertion):
  * make LruCache.__setitem__ call ``self.clear()`` instead of popitem
    -> test_a_full_cache_drops_only_the_least_recently_used_entry
  * drop the ``move_to_end`` in LruCache.__getitem__
    -> test_a_hit_protects_an_entry_from_eviction
  * make render_text.py _render_text_cached create ``{}`` instead of
    ``LruCache(500)`` -> test_the_text_cache_keeps_a_hot_entry_past_its_cap
    (the len <= 500 assertion)
  * drop the ``self.refresh_on_contains`` test in LruCache.__contains__ (always
    refresh) -> test_in_refreshes_recency_unless_told_not_to
  * delete the capacity check in LruCache.__init__
    -> test_capacity_must_be_positive
  * give client_state.py its own BoundedLRU class again
    -> test_one_class_serves_the_client_caches_and_the_render_caches
"""

from pyreborn.lru import LruCache


def test_a_full_cache_drops_only_the_least_recently_used_entry():
    cache = LruCache(3)
    for key in "abc":
        cache[key] = key
    cache["d"] = "d"
    assert list(cache) == ["b", "c", "d"]


def test_a_hit_protects_an_entry_from_eviction():
    cache = LruCache(3)
    for key in "abc":
        cache[key] = key
    assert cache.get("a") == "a"
    cache["d"] = "d"
    assert "a" in cache and "b" not in cache
    assert cache.get("zzz", 7) == 7


def test_the_text_cache_keeps_a_hot_entry_past_its_cap(make_game):
    game = make_game()
    font = game.font_small
    hot = game._render_text_cached(font, "hot", (0, 0, 0))
    for i in range(1200):
        game._render_text_cached(font, f"filler {i}", (0, 0, 0))
        assert game._render_text_cached(font, "hot", (0, 0, 0)) is hot
    assert len(game.render_cache.text_surf) <= 500


def test_one_class_serves_the_client_caches_and_the_render_caches():
    from pyreborn import client as client_module
    assert client_module.BoundedLRU is LruCache


def test_in_refreshes_recency_unless_told_not_to():
    refreshing = LruCache(2)
    plain = LruCache(2, refresh_on_contains=False)
    for cache in (refreshing, plain):
        cache["a"], cache["b"] = 1, 2
        assert "a" in cache
        cache["c"] = 3
    assert "a" in refreshing and "b" not in refreshing
    assert "a" not in plain and "b" in plain


def test_capacity_must_be_positive():
    import pytest
    with pytest.raises(ValueError):
        LruCache(0)
