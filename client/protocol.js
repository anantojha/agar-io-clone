"use strict";
// Decoder for the binary state frames. The layout is documented in server/protocol.py.
(function (root) {
  const FLAG_NAMES = 1;
  const FLAG_BOARD = 2;
  const utf8 = new TextDecoder("utf-8");

  function decodeState(buffer) {
    const view = new DataView(buffer);
    const bytes = new Uint8Array(buffer);
    if (view.getUint8(0) !== 1) throw new Error("not a state frame");
    const flags = view.getUint8(1);
    const state = {
      me: [view.getUint16(2, true), view.getUint16(4, true), view.getUint32(6, true)],
      v: view.getUint16(10, true),
    };
    const nCells = view.getUint16(12, true);
    const nFood = view.getUint16(14, true);
    const nViruses = view.getUint16(16, true);
    const nPellets = view.getUint16(18, true);
    let pos = 20;

    state.c = new Array(nCells);
    for (let i = 0; i < nCells; i++, pos += 14) {
      state.c[i] = [
        view.getUint32(pos, true), view.getUint32(pos + 4, true),
        view.getUint16(pos + 8, true), view.getUint16(pos + 10, true), view.getUint16(pos + 12, true) / 10,
      ];
    }
    state.f = new Array(nFood);
    for (let i = 0; i < nFood; i++, pos += 5) {
      state.f[i] = [view.getUint16(pos, true), view.getUint16(pos + 2, true), view.getUint8(pos + 4)];
    }
    state.vi = new Array(nViruses);
    for (let i = 0; i < nViruses; i++, pos += 6) {
      state.vi[i] = [view.getUint16(pos, true), view.getUint16(pos + 2, true), view.getUint16(pos + 4, true) / 10];
    }
    state.e = new Array(nPellets);
    for (let i = 0; i < nPellets; i++, pos += 8) {
      state.e[i] = [view.getUint16(pos, true), view.getUint16(pos + 2, true), view.getUint32(pos + 4, true)];
    }

    if (flags & FLAG_NAMES) {
      const count = view.getUint16(pos, true);
      pos += 2;
      state.n = {};
      for (let i = 0; i < count; i++) {
        const owner = view.getUint32(pos, true);
        const length = view.getUint8(pos + 4);
        pos += 5;
        state.n[owner] = utf8.decode(bytes.subarray(pos, pos + length));
        pos += length;
      }
    }
    if (flags & FLAG_BOARD) {
      const count = view.getUint8(pos);
      pos += 1;
      state.lb = [];
      for (let i = 0; i < count; i++) {
        const mass = view.getUint32(pos, true);
        const length = view.getUint8(pos + 4);
        pos += 5;
        state.lb.push([utf8.decode(bytes.subarray(pos, pos + length)), mass]);
        pos += length;
      }
    }
    return state;
  }

  const api = { decodeState };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Protocol = api;
})(typeof self !== "undefined" ? self : this);
