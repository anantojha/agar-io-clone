from game.grid import SpatialHash


class P:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def test_query_finds_nearby_and_skips_far():
    grid = SpatialHash(100)
    near, far = P(150, 150), P(1000, 1000)
    grid.insert(near)
    grid.insert(far)
    found = set(grid.query(160, 160, 50))
    assert near in found
    assert far not in found


def test_query_spans_neighboring_buckets():
    grid = SpatialHash(100)
    a, b = P(95, 50), P(105, 50)  # different buckets, 10 apart
    grid.insert(a)
    grid.insert(b)
    assert set(grid.query(100, 50, 10)) == {a, b}


def test_remove_and_clear():
    grid = SpatialHash(100)
    a, b = P(10, 10), P(20, 20)
    grid.insert(a)
    grid.insert(b)
    grid.remove(a)
    assert set(grid.query(15, 15, 50)) == {b}
    grid.clear()
    assert list(grid.query(15, 15, 50)) == []


def test_query_near_origin_does_not_wrap():
    grid = SpatialHash(100)
    a = P(5, 5)
    grid.insert(a)
    assert list(grid.query(0, 0, 500)) == [a]
