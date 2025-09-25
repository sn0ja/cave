from ..networks.network.network import Network
from dataclasses import dataclass
@dataclass
class Interface:
    mac: str
    network: Network
    ipv4_cidr: str
    is_mngmt: bool

