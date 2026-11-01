"""Binary encoding of the per-tick world snapshot. client/protocol.js decodes the same layout.

All numbers are little-endian. Positions are whole world units and radii are in tenths, so a map
up to 65535 units wide fits in u16.

    u8   type            1 = state
    u8   flags           bit 0: names follow, bit 1: leaderboard follows
    u16  me_x, me_y      center of the player's cells
    u32  me_mass
    u16  view            half-width of the square the lists cover
    u16  n_cells, n_food, n_viruses, n_pellets
    cells     n_cells    x (u32 id, u32 owner, u16 x, u16 y, u16 radius*10)
    food      n_food     x (u16 x, u16 y, u8 kind)
    viruses   n_viruses  x (u16 x, u16 y, u16 radius*10)
    pellets   n_pellets  x (u16 x, u16 y, u32 owner)
    names     if flag:   u16 count, then count x (u32 owner, u8 length, utf-8 bytes)
    board     if flag:   u8 count, then count x (u32 mass, u8 length, utf-8 bytes)

The decoder returns the same shape the first JSON protocol used:
    {"me": [x, y, mass], "v": n, "c": [[id, owner, x, y, r], ...], "f": [[x, y, kind], ...],
     "vi": [[x, y, r], ...], "e": [[x, y, owner], ...], "n": {owner: name}, "lb": [[name, mass], ...]}
"""
import struct

MSG_STATE = 1
FLAG_NAMES = 1
FLAG_BOARD = 2
MAX_COORD = 65535

_HEADER = struct.Struct("<BBHHIHHHHH")
_CELL = struct.Struct("<IIHHH")
_FOOD = struct.Struct("<HHB")
_VIRUS = struct.Struct("<HHH")
_PELLET = struct.Struct("<HHI")
_U16 = struct.Struct("<H")
_NAME = struct.Struct("<IB")


def _c(value: float) -> int:
    """A world coordinate as a u16, clamped so a stray value can't break the frame."""
    return min(max(int(round(value)), 0), MAX_COORD)


def pack_food(x: float, y: float, kind: int) -> bytes:
    """One food record. Food never moves, so callers pack it once and reuse the bytes every frame."""
    return _FOOD.pack(_c(x), _c(y), kind)


def encode_state(me, view, cells, food, viruses, pellets, names=None, leaderboard=None) -> bytes:
    """cells: (id, owner, x, y, r); food: packed records from pack_food joined into one bytes;
    viruses: (x, y, r); pellets: (x, y, owner); names: {owner: name} or None;
    leaderboard: [(name, mass)] or None."""
    flags = (FLAG_NAMES if names else 0) | (FLAG_BOARD if leaderboard is not None else 0)
    parts = [_HEADER.pack(
        MSG_STATE, flags, _c(me[0]), _c(me[1]), max(0, int(round(me[2]))), _c(view),
        len(cells), len(food) // _FOOD.size, len(viruses), len(pellets),
    )]
    parts += [_CELL.pack(i, o, _c(x), _c(y), _c(r * 10)) for i, o, x, y, r in cells]
    parts.append(food)
    parts += [_VIRUS.pack(_c(x), _c(y), _c(r * 10)) for x, y, r in viruses]
    parts += [_PELLET.pack(_c(x), _c(y), o) for x, y, o in pellets]
    if names:
        parts.append(_U16.pack(len(names)))
        for owner, name in names.items():
            raw = name.encode("utf-8")[:255]
            parts += [_NAME.pack(owner, len(raw)), raw]
    if leaderboard is not None:
        parts.append(bytes([min(len(leaderboard), 255)]))
        for name, mass in leaderboard[:255]:
            raw = name.encode("utf-8")[:255]
            parts += [_NAME.pack(max(0, int(round(mass))), len(raw)), raw]
    return b"".join(parts)


def decode_state(data: bytes) -> dict:
    kind, flags, mx, my, mass, view, n_cells, n_food, n_viruses, n_pellets = _HEADER.unpack_from(data, 0)
    if kind != MSG_STATE:
        raise ValueError(f"not a state frame: type {kind}")
    pos = _HEADER.size

    def records(struct_, count):
        nonlocal pos
        out = []
        for _ in range(count):
            out.append(struct_.unpack_from(data, pos))
            pos += struct_.size
        return out

    state = {
        "me": [mx, my, mass],
        "v": view,
        "c": [[i, o, x, y, r / 10] for i, o, x, y, r in records(_CELL, n_cells)],
        "f": [list(r) for r in records(_FOOD, n_food)],
        "vi": [[x, y, r / 10] for x, y, r in records(_VIRUS, n_viruses)],
        "e": [list(r) for r in records(_PELLET, n_pellets)],
    }
    if flags & FLAG_NAMES:
        (count,) = _U16.unpack_from(data, pos)
        pos += _U16.size
        names = {}
        for _ in range(count):
            owner, length = _NAME.unpack_from(data, pos)
            pos += _NAME.size
            names[owner] = data[pos:pos + length].decode("utf-8", "replace")
            pos += length
        state["n"] = names
    if flags & FLAG_BOARD:
        count = data[pos]
        pos += 1
        rows = []
        for _ in range(count):
            value, length = _NAME.unpack_from(data, pos)
            pos += _NAME.size
            rows.append([data[pos:pos + length].decode("utf-8", "replace"), value])
            pos += length
        state["lb"] = rows
    return state
