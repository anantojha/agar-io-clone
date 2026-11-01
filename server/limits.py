import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    """Abuse and capacity limits. Defaults suit a small free host; override with AGAR_* variables."""

    max_players: int = 25  # open connections, joined or not; measure on the real host and raise with AGAR_MAX_PLAYERS
    max_per_ip: int = 5
    msg_rate: float = 60.0  # messages per second a client may send, sustained
    msg_burst: float = 120.0
    drop_after: int = 300  # messages dropped by the rate limit before the connection is closed
    idle_timeout: float = 30.0  # seconds without any message before the connection is closed
    allowed_origins: tuple[str, ...] = ()  # empty means any origin
    trust_proxy: bool = False  # read the client address from X-Forwarded-For

    @classmethod
    def from_env(cls) -> "Limits":
        env = os.environ
        defaults = cls()
        origins = tuple(o.strip().rstrip("/") for o in env.get("AGAR_ALLOWED_ORIGINS", "").split(",") if o.strip())
        return cls(
            max_players=int(env.get("AGAR_MAX_PLAYERS", defaults.max_players)),
            max_per_ip=int(env.get("AGAR_MAX_PER_IP", defaults.max_per_ip)),
            msg_rate=float(env.get("AGAR_MSG_RATE", defaults.msg_rate)),
            msg_burst=float(env.get("AGAR_MSG_BURST", defaults.msg_burst)),
            drop_after=int(env.get("AGAR_DROP_AFTER", defaults.drop_after)),
            idle_timeout=float(env.get("AGAR_IDLE_TIMEOUT", defaults.idle_timeout)),
            allowed_origins=origins,
            trust_proxy=env.get("AGAR_TRUST_PROXY", "") == "1",
        )
