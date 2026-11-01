"""Watch bots play each other with no humans: how big do they get, and how often do they die?

    .venv/bin/python bench/sim_bots.py --bots 15 --minutes 10

Prints one line per simulated minute. Use it when tuning decay, food and bot behavior so a human
joining sees a mix of sizes instead of a few giants.
"""
import argparse
import random
import statistics
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game import Config, World  # noqa: E402
from server.bots import BotManager  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", type=int, default=15)
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--decay", type=float, help="override decay_rate")
    ap.add_argument("--food", type=int, help="override food_count")
    args = ap.parse_args()

    overrides = {}
    if args.decay is not None:
        overrides["decay_rate"] = args.decay
    if args.food is not None:
        overrides["food_count"] = args.food
    cfg = replace(Config(), **overrides)
    dt = 1 / cfg.tick_rate
    world = World(cfg, random.Random(args.seed))
    manager = BotManager(world, args.bots, random.Random(args.seed + 1))

    deaths = 0
    ticks_per_minute = cfg.tick_rate * 60
    print(f"{'min':>4} {'alive':>5} {'top':>6} {'2nd':>6} {'median':>6} {'mean':>6} {'deaths':>6} {'cells':>5}")
    for tick in range(1, int(args.minutes * ticks_per_minute) + 1):
        manager.update(tick)
        deaths += len(world.step(dt))
        if tick % ticks_per_minute == 0:
            masses = sorted((p.mass for p in world.players.values() if p.alive), reverse=True)
            cells = sum(len(p.cells) for p in world.players.values())
            top = masses[:2] + [0, 0]
            print(f"{tick // ticks_per_minute:>4} {len(masses):>5} {top[0]:>6.0f} {top[1]:>6.0f} "
                  f"{statistics.median(masses) if masses else 0:>6.0f} "
                  f"{statistics.fmean(masses) if masses else 0:>6.0f} {deaths:>6} {cells:>5}")
            deaths = 0


if __name__ == "__main__":
    main()
