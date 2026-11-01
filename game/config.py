from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # World
    map_size: float = 4000.0
    tick_rate: int = 30

    # Mass and size: radius = radius_factor * sqrt(mass), so area is proportional to mass.
    start_mass: float = 20.0
    max_mass: float = 20000.0
    radius_factor: float = 6.0

    # Movement: speed falls off as (start_mass / mass) ** speed_exponent.
    base_speed: float = 320.0  # world units per second at start_mass
    speed_exponent: float = 0.3
    min_speed: float = 60.0
    decay_rate: float = 0.005  # fraction of mass lost per second, floored at start_mass; tuned with bench/sim_bots.py

    # Eating: the eater needs eat_ratio times the victim's mass and must cover
    # the victim's center, with eat_overlap of the victim's radius as slack.
    eat_ratio: float = 1.25
    eat_overlap: float = 0.4

    # Food
    food_count: int = 1500
    food_mass: float = 1.0
    food_respawn_per_tick: int = 20

    # Splitting: a cell of at least min_split_mass halves itself and the new half is thrown toward
    # the cursor. It flies at split_speed_base + split_speed_per_radius * radius, slowing at boost_decay
    # per second. Pieces of one player can't merge until merge_base + merge_per_mass * mass seconds pass.
    max_cells: int = 16
    min_split_mass: float = 40.0
    split_speed_base: float = 600.0
    split_speed_per_radius: float = 6.0
    boost_decay: float = 5.0
    split_cooldown: float = 0.25
    merge_base: float = 10.0
    merge_per_mass: float = 0.01

    # Ejecting: each cell of at least min_eject_mass pays eject_cost and throws a pellet worth
    # pellet_mass that anyone can eat once it has slowed down.
    min_eject_mass: float = 30.0
    eject_cost: float = 14.0
    pellet_mass: float = 12.0
    eject_speed: float = 700.0
    pellet_decay: float = 4.0
    eject_cooldown: float = 0.1
    max_pellets: int = 400
    pellet_lifetime: float = 60.0
    pellet_edible_speed: float = 40.0

    # Viruses: stationary. A cell that can eat one (eat_ratio times its mass) bursts into pieces instead.
    virus_count: int = 12
    virus_mass: float = 100.0
    virus_pieces: int = 8

    # Food is looked up per bucket by the network layer, so its buckets are smaller (less food
    # sent outside the view).
    food_grid_cell_size: float = 128.0

    # Spatial hash bucket size, about the size of a starting cell's neighborhood.
    grid_cell_size: float = 256.0

    # Spawning: how many random spots to compare, picking the one farthest from other cells.
    spawn_candidates: int = 8
