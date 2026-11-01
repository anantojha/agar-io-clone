"""Time World.step() with N bots wandering around.

    .venv/bin/python bench/bench_tick.py --players 50 --ticks 600

The tick budget at 30 Hz is 33 ms. A free host with a fraction of a vCPU is many times
slower than a laptop core, so the number to watch is how much of the budget this uses here.
"""
import argparse
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game import Config, World  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=50)
    ap.add_argument("--ticks", type=int, default=600)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--split", action="store_true",
                    help="worst case: everyone starts huge and keeps splitting and ejecting")
    args = ap.parse_args()

    cfg = Config()
    dt = 1 / cfg.tick_rate
    world = World(cfg, random.Random(args.seed))
    bot_rng = random.Random(args.seed + 1)
    for i in range(args.players):
        player = world.add_player(f"bot{i}")
        if args.split:
            player.cells[0].mass = 4000

    samples = []
    deaths = 0
    for tick in range(args.ticks):
        if tick % 15 == 0:
            for p in world.players.values():
                if not p.alive:
                    world.respawn(p.id)
                    continue
                cell = p.cells[0]
                world.set_target(
                    p.id,
                    cell.x + bot_rng.uniform(-600, 600),
                    cell.y + bot_rng.uniform(-600, 600),
                )
        if args.split and tick % 10 == 0:
            for p in world.players.values():
                world.split(p.id)
                world.eject(p.id)
        t0 = time.perf_counter()
        deaths += len(world.step(dt))
        samples.append((time.perf_counter() - t0) * 1000)

    samples.sort()
    budget = dt * 1000
    mean = statistics.fmean(samples)
    cells = sum(len(p.cells) for p in world.players.values())
    print(f"players={args.players} cells={cells} food={len(world.food)} pellets={len(world.pellets)} "
          f"viruses={len(world.viruses)} ticks={args.ticks} deaths={deaths}")
    print(f"step ms: mean={mean:.2f} p95={samples[int(len(samples) * 0.95)]:.2f} max={samples[-1]:.2f}")
    print(f"budget {budget:.1f} ms/tick; mean uses {mean / budget * 100:.1f}% of one core here")


if __name__ == "__main__":
    main()
