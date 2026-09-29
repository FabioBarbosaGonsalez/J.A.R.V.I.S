from app.cache import Cache


def test_set_get_and_expiry(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    cache.set("a", {"x": [1, "ação"]}, ttl_seconds=60)
    cache.set("b", 1, ttl_seconds=-1)  # já vencido

    assert cache.get("a").value == {"x": [1, "ação"]}
    assert cache.get("b") is None
    assert cache.get_stale("b").value == 1  # vencido, mas ainda disponível como reserva
    assert cache.get_stale("nada") is None


def test_persists_between_instances(tmp_path):
    Cache(tmp_path / "c.sqlite3").set("k", "v", ttl_seconds=60)
    assert Cache(tmp_path / "c.sqlite3").get("k").value == "v"


def test_increment(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    assert cache.increment("n", ttl_seconds=60) == 1
    assert cache.increment("n", ttl_seconds=60) == 2
