import libvirt
import sys
sys.path.append('../cave')

# setting path
from cave import Interface 
from cave import Range
import json, os
import subprocess
import logging

HOST = "192.168.188.26"
REMOTE_IMAGES_DIR = "/opt/test/images"
REMOTE_POOL_DIR = "/opt/test/pool1"

CON_URI = f"qemu+ssh://root@{HOST}/system"
SSH_URI = f"root@{HOST}"
TMP_CLOUD_INIT_DIR = "/tmp/cloud_init"

UBUNTU_IMAGE = "/opt/IMG/noble-server-cloudimg-amd64.qcow2"
WINDOWS_SERVER_ISO = "/opt/ISO/winserver22.iso"
LOCAL_IMAGE_PATHS = [WINDOWS_SERVER_ISO, UBUNTU_IMAGE]

USERNAME = "user"
PASSWORD = "banga"

SSH_PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKXiXbuBe8utnnR7RlgihIlJMDTB8i+92+hLl97uHw18"
SSH_PRIV_PATH = "/home/snoja/.ssh/bac/test"
LOGGER = logging.getLogger()
### setup host for test run, push image/iso if it does not exits
return_code = subprocess.call(["ssh", SSH_URI, f"mkdir -p {TMP_CLOUD_INIT_DIR} {REMOTE_IMAGES_DIR} {REMOTE_POOL_DIR}"], stdout=subprocess.DEVNULL)

for local_image_path in LOCAL_IMAGE_PATHS:
    # upload images
    file_name = os.path.basename(local_image_path)
    remote_image_path = f"{REMOTE_IMAGES_DIR}/{file_name}"
    return_code = subprocess.call(["ssh", SSH_URI, f"test -f {remote_image_path}"], stdout=subprocess.DEVNULL)
    if return_code != 0:
        return_code = subprocess.call(["scp", local_image_path, f"{SSH_URI}:{remote_image_path}"], stdout=subprocess.DEVNULL)
        assert return_code == 0, f"Upload of image {local_image_path} to {remote_image_path} failed"
    else:
        LOGGER.info(f"{file_name}")

conn = libvirt.open(CON_URI)

range = Range(conn, SSH_URI, TMP_CLOUD_INIT_DIR, SSH_PUB, USERNAME, PASSWORD)
range.nuke_libvirt()
range.add_pool("pool1",REMOTE_POOL_DIR)

# isolated network
mngt = range.add_management_network(name="mngmt", 
                         ipv4_cidr="10.10.0.1/24")

n1 = range.add_network(name="network1", 
                       ipv4_cidr="",
                       mode="")

i1 = Interface(mac="", 
               network=n1, 
               ipv4_cidr="10.10.1.2/24", 
               is_mngmt=False) 

im = Interface(mac="", 
               network=mngt, 
               ipv4_cidr="10.10.0.2/24", 
               is_mngmt=True) 

ubuntu_img = f"{REMOTE_IMAGES_DIR}/{os.path.basename(UBUNTU_IMAGE)}"
ld = range.add_linux_domain(name="linux01", 
                            hostname="lin01", 
                            base_image_path=ubuntu_img, 
                            interfaces=[i1, im],
                            graphics_passwd="pw",
                            disk_volume_size_gb=8,
                            memory=1024,
                            vcpus=2,
                            graphics_port="6000",
                            graphics_auto_port="no", 
                            graphics_address="0.0.0.0",
                            default_gateway="10.10.1.1",
                            dns_server="1.1.1.1",
                            management_default_gateway="10.10.0.1") 

i1 = Interface(mac="", 
               network=n1, 
               ipv4_cidr="10.10.1.4/24", 
               is_mngmt=False) 

im = Interface(mac="", 
               network=mngt, 
               ipv4_cidr="10.10.0.4/24", 
               is_mngmt=True) 

ld = range.add_linux_domain("linux02", "lin02", ubuntu_img, [i1, im], "pw", 8, 1024, 2, "6001", "no", "0.0.0.0", "10.10.1.1", "1.1.1.1", "10.10.0.1") 

i1 = Interface(mac="", 
               network=n1, 
               ipv4_cidr="10.10.1.3/24", 
               is_mngmt=False) 

im = Interface(mac="", 
               network=mngt, 
               ipv4_cidr="10.10.0.3",
               is_mngmt=True) 

windows_server22_iso = f"{REMOTE_IMAGES_DIR}/{os.path.basename(WINDOWS_SERVER_ISO)}"
wd = range.add_windows_server_domain("windows01", "win01", windows_server22_iso, None, 2, [i1,im],"pw", 20, 3000, 2, "6002", "no", "0.0.0.0", "10.10.1.1", "1.1.1.1", "10.10.0.1" )

range.block_unil_rdy()

# TODO: cleanup

# testcase whoami
LOGGER.info("testcase whoami")

# windows01
return_val = subprocess.check_output(["ssh", "-i", SSH_PRIV_PATH, "-o", "UserKnownHostsFile /dev/null", "-o StrictHostKeyChecking=no", f"{USERNAME}@10.10.0.3", f'PowerShell -Command "echo $Env:UserName"'])
assert return_val.decode().startswith(USERNAME)

# linux01
return_val = subprocess.check_output(["ssh", "-i", SSH_PRIV_PATH, "-o", "UserKnownHostsFile /dev/null", "-o StrictHostKeyChecking=no", f"{USERNAME}@10.10.0.2", f'whoami'])
assert return_val.decode().startswith(USERNAME)

# linux02
return_val = subprocess.check_output(["ssh", "-i", SSH_PRIV_PATH, "-o", "UserKnownHostsFile /dev/null", "-o StrictHostKeyChecking=no", f"{USERNAME}@10.10.0.4", f'whoami'])
assert return_val.decode().startswith(USERNAME)

# network/ping tests
# windows01
return_val = subprocess.call(["ssh", "-i", SSH_PRIV_PATH, "-o", "UserKnownHostsFile /dev/null", "-o StrictHostKeyChecking=no", f"{USERNAME}@10.10.0.3", f'PowerShell -Command "(ping 10.10.1.2) -and (ping 10.10.1.4)"'])
assert return_val == 0

# linux01
return_val = subprocess.call(["ssh", "-i", SSH_PRIV_PATH, "-o", "UserKnownHostsFile /dev/null", "-o StrictHostKeyChecking=no", f"{USERNAME}@10.10.0.2", f'ping 10.10.1.3 -c 2 -4 && ping 10.10.1.4 -c 2 -4'])
assert return_val == 0

# linux02
return_val = subprocess.call(["ssh", "-i", SSH_PRIV_PATH, "-o", "UserKnownHostsFile /dev/null", "-o StrictHostKeyChecking=no", f"{USERNAME}@10.10.0.4", f'ping 10.10.1.2 -c 2 -4 && ping 10.10.1.3 -c 2 -4'])
assert return_val == 0

range.cleanup()
