import os 
import ipaddress
import jinja2
import re

from libvirt import virConnect


def cidr_to_netmask(cidr: str) -> tuple[str, str]:
    """
    Converts an IPv4 address in CIDR notation into a tuple of IP address and network mask. 

    Parameters
    ----------
    cidr : str
        IPv4 address in CIDR notation.

    Returns
    -------
    tuple[str, str]
        Tuple of IP address and netmask.
    """
    interface = ipaddress.IPv4Interface(cidr)
    address, netmask = interface.with_netmask.split("/")
    return address, netmask

class Network(object):
    """
    Object defining a network in the libvirt cyber range.

    Parameters
    ----------
    name : str
        Name of the network to be defined
    host_isolated : bool, default: False
        If the libvirt host should be isolated from the systems in the range.
    ipv4_cidr : str, optional
        IPv4 address in CIDR notation which the libvirt host should use.
    isolate_guest : bool, default: False
        If the guests on this network should be isolated from eachother.
    ipv6_cidr: str, optional
        The IPv6 addrtess for the libvirt host in CIDR notation.
    mode : str, optional
        Network mode for the network.
    ingress_route_subnet : str, optional
        Subnet the libvirt host should route into the cyber range.
    ingress_route_gateway : str, optional
        Nexthop to use for routing traffic into the cyber range.
    """
    RELATIVE_TEMPLATE_PATH = "network.jinja.xml"

    def __init__(
        self,
        name: str,
        host_isolated: bool = False,
        ipv4_cidr: str = "",
        isolate_guests: bool = False,
        ipv6_cidr: str = "",
        mode: str = "",
        ingress_route_subnet: str = "",
        ingress_route_gateway: str = "" 
    ):
    
        if ipv4_cidr:
            ipv4_tuple = cidr_to_netmask(ipv4_cidr)
            self.ipv4 = ipv4_tuple[0]
            self.ipv4_subnet = ipv4_tuple[1]
        else:
            self.ipv4 = ""
            self.ipv4_subnet = ""

        if ipv6_cidr:
            ipv6_tuple = ipv6_cidr.split("/")
            self.ipv6 = ipv6_tuple[0]
            self.ipv6_prefix = ipv6_tuple[1]
        else:
            self.ipv6 = ""
            self.ipv6_subnet = ""


        self.name = name
        self.mode = mode
        self.host_isolated = host_isolated
        self.isolate_guests = "yes" if isolate_guests else "no"
        self.host_mac = None
        self.ingress_route_subnet = ipaddress.ip_network(ingress_route_subnet) if ingress_route_subnet else None
        self.ingress_route_gateway = ingress_route_gateway if ingress_route_gateway else None



    def _get_config(self) -> dict:
        """
        Turns the current configuration into a dictionary.

        Returns
        -------
        dict
            The curent configuration.
        """
        config = {
            "name": self.name,
            "mode": self.mode,
            "ipv4": self.ipv4,
            "ipv6": self.ipv6,
            "ipv4_subnetmask": self.ipv4_subnet,
            "ipv6_prefix": self.ipv6_prefix,
            "host_isolated": self.host_isolated,
            "isolate_guests": self.isolate_guests,
            "ingress_route_subnet_ip":  str(self.ingress_route_subnet.network_address) if self.ingress_route_subnet else None,
            "ingress_route_subnet_prefix_length": str(self.ingress_route_subnet.prefixlen) if self.ingress_route_subnet else None,
            "ingress_route_gateway": self.ingress_route_gateway 
            
        }
        return config

    def to_dict(self) -> dict:
        """
        Returns dict of name and mode.

        Returns
        -------
        dict
            Name and mode of the network.
        """
        return {"name":self.name,
                "mode":self.mode}

    def get_host_mac_from_xml(self) -> str:
        """
        Retrieves the MAC address of the network from the definition XML.

        Returns
        -------
        str
            MAC address of the network.
        """
        #<mac address='52:54:00:0e:4b:74'/>
        assert self.libvirt_network
        matches = re.search(r"<mac address='(?P<mac>.*)'/>", self.libvirt_network.XMLDesc())
        if not matches:
            raise Exception(f"no mac found in in network definition for {self.name} unable to set isolate host iptables rules")
        return matches.group('mac')

    def create(self, conn: virConnect):
        """
        Creates the network defined by this object.

        Parameters
        ----------
        conn : virConnect
            The connection to the libvirt host, where the network should be created.
        """
        # lookupByName throws if the name is not found
        template_path = f"{os.path.dirname(
            __file__)}/{Network.RELATIVE_TEMPLATE_PATH}"
        with open(template_path, "r") as f:
            template = jinja2.Template(f.read())
            xml_content = template.render(self._get_config())
            self.libvirt_network = conn.networkDefineXML(xml_content)
            self.libvirt_network.create()
            self.host_mac = self.get_host_mac_from_xml()
    
    def remove(self):
        """Removes the network."""
        assert self.libvirt_network
        if self.libvirt_network.isPersistent():
            self.libvirt_network.undefine()
        if self.libvirt_network.isActive():
            self.libvirt_network.destroy()

    @staticmethod
    def destroy_by_name(conn: virConnect, name: str):
        """
        Destroys a network by a given name.

        Parameters
        ----------
        conn : virConnect
            Libvirt conection where the network should be destroyed.
        name : str
            Name of the network which should be destroyed.
        """
        network = conn.networkLookupByName(name)
        network.destroy()
        network.undefine()
        
