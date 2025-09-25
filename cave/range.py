import libvirt
from .src import Pool
from .src import Network
from .src import OsType
from .src import LinuxDomain
from .src import Interface
from .src import CloudInitMetaData, CloudInitUserConfig, CloudInitNetworkConfig
from .src import create_and_push_cd
from .src import Autounattend
from .src import WindowsDomain
from .src import WindowsDomain
from .src import AutounattendServer
from .src import WindowsTPMDomain
from .src import AutounattendGPT

import uuid
import logging
import socket
from time import sleep
from random import randint
import sys

root = logging.getLogger("default")
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
root.addHandler(handler)
logger = logging.getLogger("default")

def random_mac():
    return "02:00:00:%02x:%02x:%02x" % (randint(0, 255),
                                        randint(0, 255),
                                        randint(0, 255))

class Range():
    def __init__(self, libvirt_connection, ssh_connect_uri: str, remote_autoinstall_iso_path: str, domain_ssh_pub_key: str, domain_user: str, domain_password: str):
        self.libvirt_connection = libvirt_connection
        self.ssh_connect_uri = ssh_connect_uri
        self.remote_autoinstall_iso_path = remote_autoinstall_iso_path
        self.domain_user = domain_user
        self.domain_password = domain_password
        self.domain_ssh_pub_key = domain_ssh_pub_key
        self.pool = None
        self.networks = []
        self.domains = []
        self.management_network = None

    def add_pool(self, name: str, path: str):
        self.pool = Pool(name, path)
        self.pool.create(self.libvirt_connection)
        return self.pool
         
    def add_network(self, name: str, mode: str, ipv4_cidr: str, ingress_route_subnet: str="", ingress_route_gateway: str="") -> Network:

        n = Network(name=name, 
                    host_isolated=True if mode == "" else False, 
                    ipv4_cidr=ipv4_cidr, 
                    isolate_guests=False,
                    ipv6_cidr="",  
                    mode=mode, 
                    ingress_route_subnet=ingress_route_subnet, ingress_route_gateway=ingress_route_gateway)


        n.create(self.libvirt_connection)
        self.networks.append(n)
        return n

    def add_management_network(self, name: str, ipv4_cidr: str, ):
        if self.management_network:
            logger.error("Multiple management networks for a single range is not supported for now")
            return

        n = Network(name=name, 
                    host_isolated=False, 
                    ipv4_cidr=ipv4_cidr, 
                    isolate_guests=False,
                    ipv6_cidr="", 
                    mode="open", 
                    ingress_route_subnet="", ingress_route_gateway="")

        n.create(self.libvirt_connection)
        self.networks.append(n)
        self.management_network = n
        return n



    def add_linux_domain(self, name: str, hostname: str, base_image_path: str, interfaces: list[Interface], graphics_passwd: str,  disk_volume_size_gb: int, memory: int, vcpus: int, graphics_port: str, graphics_auto_port: str, graphics_address: str, default_gateway: str, dns_server: str, management_default_gateway: str):
        """
            Args:
        """
        if not self.pool:
            logger.error(f"cannot create linux domain before pool was created")
        assert self.pool

        # generate random macs for interfaces without mac
        for interface in interfaces:
            if len(interface.mac) == 0:
                interface.mac = random_mac()
        
        meta_data = CloudInitMetaData(hostname=hostname, instance_id=str(uuid.uuid4())) 
        user_config = CloudInitUserConfig(self.domain_user, 
                        self.domain_password,
                        self.domain_ssh_pub_key 
                        )
        network_config = CloudInitNetworkConfig(interfaces, 
                            range_default_gateway=default_gateway,
                            range_dns_server=dns_server, 
                            management_default_gateway=management_default_gateway)
        
        cdrom_files = {CloudInitMetaData.CLOUDINIT_FILE_NAME:str(meta_data), 
                        CloudInitUserConfig.CLOUDINIT_FILE_NAME:str(user_config),
                        CloudInitNetworkConfig.CLOUDINIT_FILE_NAME:str(network_config)}

        remote_path = create_and_push_cd(f"{self.remote_autoinstall_iso_path}/{uuid.uuid4()}.iso", self.ssh_connect_uri, cdrom_files)

        volume = self.pool.create_volume(f"{name}_vol", disk_volume_size_gb, base_image_path, format="qcow2")
        linux_domain = LinuxDomain(name, volume, interfaces, graphics_passwd, remote_path, memory, vcpus, graphics_port, graphics_auto_port, graphics_address, OsType.GENERIC_LINUX)
        linux_domain.create(self.libvirt_connection)
        self.domains.append(linux_domain)
        return linux_domain

    def add_windows_domain(self, name: str, hostname: str, boot_iso: str, product_key: str, interfaces: list[Interface], graphics_passwd: str,  disk_volume_size_gb: int, memory: int, vcpus: int, graphics_port: str, graphics_auto_port: str, graphics_address: str, default_gateway: str, dns_server: str, management_default_gateway: str):
        if not self.pool:
            logger.error(f"cannot create windows domain before pool was created")

        assert self.pool

        # generate random macs for interfaces without mac
        for interface in interfaces:
            if len(interface.mac) == 0:
                interface.mac = random_mac()
        
        
        unattend = Autounattend(interfaces=interfaces, 
                        username=self.domain_user,
                        ssh_pub=self.domain_ssh_pub_key,
                        password=self.domain_password,
                        hostname=hostname,
                        management_default_gateway=management_default_gateway,
                        range_default_gateway=default_gateway,
                        range_dns_server=dns_server,
                        product_key=product_key
                        )

        cdrom_files = {"Autounattend.xml":str(unattend)}
        remote_path = create_and_push_cd(f"{self.remote_autoinstall_iso_path}/{uuid.uuid4()}.iso", self.ssh_connect_uri, cdrom_files)

        volume = self.pool.create_volume(f"{name}_vol", disk_volume_size_gb, None, format="raw")

        wd = WindowsDomain(name, volume, boot_iso, interfaces, graphics_passwd, remote_path, memory, vcpus, graphics_port, graphics_auto_port, graphics_address, OsType.GENERIC_WINDOWS)

        wd.create(self.libvirt_connection)
        self.domains.append(wd)
        return wd

    def add_windows_server_domain(self, name: str, hostname: str, boot_iso: str, product_key: str|None, version_index: int|None, interfaces: list[Interface], graphics_passwd: str,  disk_volume_size_gb: int, memory: int, vcpus: int, graphics_port: str, graphics_auto_port: str, graphics_address: str, default_gateway: str, dns_server: str, management_default_gateway: str):
        if not self.pool:
            logger.error(f"cannot create windows server domain before pool was created")

        assert self.pool

        # generate random macs for interfaces without mac
        for interface in interfaces:
            if len(interface.mac) == 0:
                interface.mac = random_mac()
        
        
        unattend = AutounattendServer(interfaces=interfaces, 
                        username=self.domain_user,
                        ssh_pub=self.domain_ssh_pub_key,
                        password=self.domain_password,
                        hostname=hostname,
                        management_default_gateway=management_default_gateway,
                        range_default_gateway=default_gateway,
                        range_dns_server=dns_server,
                        version_index=version_index,
                        product_key=None,
                        )

        cdrom_files = {"Autounattend.xml":str(unattend)}
        remote_path = create_and_push_cd(f"{self.remote_autoinstall_iso_path}/{uuid.uuid4()}.iso", self.ssh_connect_uri, cdrom_files)

        volume = self.pool.create_volume(f"{name}_vol", disk_volume_size_gb, None, format="raw")

        wd = WindowsDomain(name, volume, boot_iso, interfaces, graphics_passwd, remote_path, memory, vcpus, graphics_port, graphics_auto_port, graphics_address, OsType.GENERIC_WINDOWS_SERVER)

        wd.create(self.libvirt_connection)
        self.domains.append(wd)
        return wd

    def add_windows_tpm_domain(self, name: str, hostname: str, boot_iso: str, product_key: str, interfaces: list[Interface], graphics_passwd: str,  disk_volume_size_gb: int, memory: int, vcpus: int, graphics_port: str, graphics_auto_port: str, graphics_address: str, default_gateway: str, dns_server: str, management_default_gateway: str):
        if not self.pool:
            logger.error(f"cannot create windows domain before pool was created")

        assert self.pool

        # generate random macs for interfaces without mac
        for interface in interfaces:
            if len(interface.mac) == 0:
                interface.mac = random_mac()
        
        
        unattend = AutounattendGPT(interfaces=interfaces, 
                        username=self.domain_user,
                        ssh_pub=self.domain_ssh_pub_key,
                        password=self.domain_password,
                        hostname=hostname,
                        management_default_gateway=management_default_gateway,
                        range_default_gateway=default_gateway,
                        range_dns_server=dns_server,
                        product_key=product_key
                        )

        cdrom_files = {"Autounattend.xml":str(unattend)}
        remote_path = create_and_push_cd(f"{self.remote_autoinstall_iso_path}/{uuid.uuid4()}.iso", self.ssh_connect_uri, cdrom_files)

        volume = self.pool.create_volume(f"{name}_vol", disk_volume_size_gb, None, format="raw")

        wd = WindowsTPMDomain(name, volume, boot_iso, interfaces, graphics_passwd, remote_path, memory, vcpus, graphics_port, graphics_auto_port, graphics_address, OsType.WINDOWS_TPM)

        wd.create(self.libvirt_connection)
        self.domains.append(wd)
        return wd

    def nuke_libvirt(self):
        # Get list of all pool names (active and inactive)
        logger.info(f"nuking pools and volumes")
        pools = self.libvirt_connection.listAllStoragePools()
        for pool in pools:
            try:
                logger.info(f"Processing pool: {pool.name()}")

                # Delete all volumes in the pool
                volumes = pool.listAllVolumes()
                for volume in volumes:
                    logger.info(f"Deleting volume: {volume.name()}")
                    volume.delete(0)

                # Destroy the pool if active
                if pool.isActive():
                    logger.info(f"Destroying pool: {pool.name()}")
                    pool.destroy()

                # Undefine the pool (removes it from libvirt config)
                logger.info(f"Undefining pool: {pool.name()}")
                pool.undefine()

            except libvirt.libvirtError as e:
                logger.error(f"Error processing pool '{pool.name()}': {e}")
        logger.info("All pools and volumes destroyed.")

        logger.info("Nuking domains")
        domains = self.libvirt_connection.listAllDomains()

        for domain in domains:
            try:
                if domain.isActive():
                    domain.destroy()
                if domain.isPersistent():
                    # 0x4: also undefine nvram
                    domain.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_NVRAM)
            except libvirt.libvirtError as e:
                logger.error(f"Error processing domain '{domain.name()}': {e}")

        logger.info("Nuking networks")
        networks = self.libvirt_connection.listAllNetworks()

        for network in networks:
            try:
                if network.isActive():
                    network.destroy()
                if network.isPersistent():
                    network.undefine()
            except libvirt.libvirtError as e:
                logger.error(f"Error processing network '{network.name()}': {e}")

    def get_state(self):
        assert self.pool
        return {"domains":[domain.to_dict() for domain in self.domains], "networks": [network.to_dict() for network in self.networks], "pool": {"name":self.pool.name, "path":self.pool.path}}

    def cleanup(self):
        logger.info(f"removing management network {self.management_network.name} {self.management_network.libvirt_network.name()}")
        for domain in self.domains:
            logger.info(f"removing management network interface for domain {domain.name}")
            domain.remove_interface_for_network_name(self.management_network.name)
        self.management_network.remove()
        self.networks.remove(self.management_network)
        logger.info(f"done removing management network {self.management_network.name}")

    def block_unil_rdy(self):
        for domain in self.domains:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            ipv4 = domain.get_mngmt_ipv4()
            result = 1
            logger.info(f"waiting for {domain.name} to be reachable")
            while result != 0:
                result = sock.connect_ex((ipv4, 22))
                sleep(5)
            logger.info(f"{domain.name} is up.")
            sock.close()
