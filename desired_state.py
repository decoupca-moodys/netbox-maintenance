from concurrent.futures import ThreadPoolExecutor
from netbox import NetBox
import config
import logging
import ipdb
from pprint import pprint
import re


HOSTNAME_PATTERN=r'^(?P<role>\w{1})(?P<site>\w{3})(?P<floor>\d{2})(?P<subrole>\w{2})(?P<index>\d{2})$'

DEVICE_TAGS = [
    {'name': 'Switch - Access', 'slug': 'switch-access'},
    {'name': 'Switch - Distribution', 'slug': 'switch-distribution'},
    {'name': 'Primary', 'slug': 'primary'},
    {'name': 'Secondary', 'slug': 'secondary'},
    {'name': 'Layer 3', 'slug': 'l3'},
    {'name': 'Layer 2', 'slug': 'l2'},
]

HOSTNAME_ROLE_TAG_MAP = {
    'R': 'router',
    'S': 'switch',
    'W': 'wireless-controller',
}

HOSTNAME_SUBROLE_TAG_MAP = {
    'AC': 'switch-access',
    'DC': 'switch-distribution',
    'SS': 'switch-server',
    'VG': 'voice-gateway',
    'WC': 'wireless-controller',
    'TS': 'console-server',
    'LB': 'load-balancer',
    'WA': 'wan-router', # Legacy
    'ER': 'edge-router', # New, Fulcrum
}

PLATFORM_TAG_MAP = {
    "Network-Arista": "eos",
    "Network-IOS": "ios",
    "Network-IOS-XE": "ios_xe",
    "Network-Juniper": "junos",
    "Network-NXOS": "nxos",
    "Network-Riverbed": "riverbed",
    "Network-WLC": "aireos",
}



root_log = logging.getLogger()
log = logging.getLogger("update_netbox")
log.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(name)s %(levelname)s: %(message)s")
handler.setFormatter(formatter)
root_log.addHandler(handler)

netbox_args = {
    "host": config.netbox_host,
    "auth_token": config.netbox_token,
    "use_ssl": True,
    "ssl_verify": True,
}

netbox = NetBox(**netbox_args)
platforms = netbox.dcim.get_platforms()
devices = netbox.dcim.get_devices(has_primary_ip=True, site='WTC')
def get_platform_id(platform_slug):
    for platform in platforms:
        if platform["slug"] == platform_slug:
            return platform["id"]


def verify_platform(device):
    if device["platform"]:
        log.info(
            f'{device["name"]}: Platform already set to "{device["platform"]["slug"]}", doing nothing'
        )
    else:
        tag = device["tags"][0]
        log.debug(f'{device["name"]}: Tag: "{tag}"')
        platform_slug = PLATFORM_TAG_MAP.get(tag)
        log.debug(f'{device["name"]}: Platform slug: "{platform_slug}"')
        if platform_slug:
            platform_id = get_platform_id(platform_slug)
            log.debug(f'{device["name"]}: Platform ID: "{platform_id}"')
            netbox.dcim.update_device_by_id(
                device_id=device["id"], platform=platform_id
            )
            log.info(f'{device["name"]}: Updated platform to "{platform_slug}"')
        else:
            log.info(
                f'{device["name"]}: No platform mapped for tag {tag}, doing nothing'
            )


def verify_all_platforms(devices):
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        return executor.map(verify_platform, devices)


def parse_hostname(device):
    """ Parses a hostname into properties dict """
    pattern = re.compile(HOSTNAME_PATTERN)
    parsed_hostname = pattern.search(device["name"])
    if parsed_hostname:
        device_role = parsed_hostname.group('role')
        device_site = parsed_hostname.group('site')
        device_floor = parsed_hostname.group('floor')
        device_subrole = parsed_hostname.group('subrole')
        device_index = parsed_hostname.group('index')

        device.update({'parsed_props': {
            'device_role': HOSTNAME_ROLE_TAG_MAP.get(device_role) or device_role,
            'device_site': device_site,
            'device_floor': int(device_floor),
            'device_subrole': HOSTNAME_SUBROLE_TAG_MAP.get(device_subrole) or device_subrole,
            'device_index': int(device_index),
        }})
    else:
        device.update({'parsed_props': None})
    return device
    

def verify_tags(device):
    pass

def verify_all_tags(device):
    pass

def main():
    #verify_all_platforms(devices)
    for device in devices:
        device = parse_hostname(device)
        print(device['name'])
        pprint(device['parsed_props'])

if __name__ == "__main__":
    main()
