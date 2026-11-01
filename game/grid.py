from typing import Iterator


class SpatialHash:
    """Bucketed lookup for objects with x and y attributes.

    query() returns every object in the buckets that overlap the search square, so callers
    still do their own exact distance check. Coordinates must be non-negative, and an object
    must not move between insert() and remove().
    """

    __slots__ = ("cell_size", "_buckets", "dirty")

    def __init__(self, cell_size: float):
        self.cell_size = cell_size
        self._buckets: dict[tuple[int, int], set] = {}
        # Keys of buckets whose contents changed since a caller last cleared this, so a cache
        # built per bucket knows what to rebuild.
        self.dirty: set[tuple[int, int]] = set()

    def insert(self, obj) -> None:
        key = (int(obj.x // self.cell_size), int(obj.y // self.cell_size))
        bucket = self._buckets.get(key)
        if bucket is None:
            self._buckets[key] = {obj}
        else:
            bucket.add(obj)
        self.dirty.add(key)

    def remove(self, obj) -> None:
        key = (int(obj.x // self.cell_size), int(obj.y // self.cell_size))
        bucket = self._buckets.get(key)
        if bucket is not None:
            bucket.discard(obj)
            if not bucket:
                del self._buckets[key]
            self.dirty.add(key)

    def items_at(self, key: tuple[int, int]) -> set:
        return self._buckets.get(key) or set()

    def keys_in(self, x: float, y: float, radius: float):
        """Keys of every bucket the square around (x, y) touches, whether or not it holds anything."""
        cs = self.cell_size
        x0 = int(max(x - radius, 0.0) // cs)
        x1 = int((x + radius) // cs)
        y0 = int(max(y - radius, 0.0) // cs)
        y1 = int((y + radius) // cs)
        return [(gx, gy) for gx in range(x0, x1 + 1) for gy in range(y0, y1 + 1)]

    def clear(self) -> None:
        self._buckets = {}
        self.dirty = set()

    def query_list(self, x: float, y: float, radius: float) -> list:
        """Same objects as query(), as a list. Cheaper when the caller wants all of them anyway."""
        cs = self.cell_size
        x0 = int(max(x - radius, 0.0) // cs)
        x1 = int((x + radius) // cs)
        y0 = int(max(y - radius, 0.0) // cs)
        y1 = int((y + radius) // cs)
        buckets = self._buckets
        out: list = []
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                bucket = buckets.get((gx, gy))
                if bucket:
                    out.extend(bucket)
        return out

    def query(self, x: float, y: float, radius: float) -> Iterator:
        cs = self.cell_size
        x0 = int(max(x - radius, 0.0) // cs)
        x1 = int((x + radius) // cs)
        y0 = int(max(y - radius, 0.0) // cs)
        y1 = int((y + radius) // cs)
        buckets = self._buckets
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                bucket = buckets.get((gx, gy))
                if bucket:
                    yield from bucket
