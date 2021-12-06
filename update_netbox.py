from concurrent.futures import ThreadPoolExecutor
from netbox import NetBox
import config
import logging
import ipdb
from pprint import pprint
import re


HOSTNAME_PATTERN = r"^(?P<role>\w{1})(?P<site>\w{3})(?P<floor>\d{2})(?P<subrole>\w{2})(?P<index>\d{2}).*$"

DEVICE_TAGS = [
    "core-router",
    "edge-router",
    "edge-router",
    "layer2",
    "layer3",
    "load-balancer",
    "primary",
    "secondary",
    "switch-access",
    "switch-distribution",
    "voice-gateway",
    "wan-accelerator",
]

HOSTNAME_ROLE_TAG_MAP = {
    "O": "wan-accelerator",
    "R": "router",
    "S": "switch",
    "V": "voice-gateway",
    "W": "wireless-controller",
}

HOSTNAME_SUBROLE_TAG_MAP = {
    "AC": "switch-access",
    "CR": "core-router",
    "DS": "switch-distribution",
    "ER": "edge-router",  # New, Fulcrum
    "LB": "load-balancer",
    "SS": "switch-server",
    "TS": "console-server",
    "VG": "voice-gateway",
    "WA": "wan-router",  # Legacy
    "WC": "wireless-controller",
    "WO": "wan-accelerator",
}

PLATFORM_TAG_MAP = {
    "Network-Arista": "eos",
    "Network-IOS": "ios",
    "Network-IOS-XE": "ios",
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
devices = netbox.dcim.get_devices(has_primary_ip=True, site="MAD")
#ipdb.set_trace()

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


def map_threads(worker, devices):
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        return executor.map(worker, devices)

def verify_all_platforms(devices):
    return map_threads(verify_platforms, devices)

def parse_hostname(device):
    """Parses a hostname into properties dict"""
    pattern = re.compile(HOSTNAME_PATTERN)
    parsed_hostname = pattern.search(device["name"])
    if parsed_hostname:
        device_role = parsed_hostname.group("role")
        device_site = parsed_hostname.group("site")
        device_floor = parsed_hostname.group("floor")
        device_subrole = parsed_hostname.group("subrole")
        device_index = parsed_hostname.group("index")

        device.update(
            {
                "parsed_props": {
                    "device_role": HOSTNAME_ROLE_TAG_MAP.get(device_role)
                    or device_role,
                    "device_site": device_site,
                    "device_floor": int(device_floor),
                    "device_subrole": HOSTNAME_SUBROLE_TAG_MAP.get(device_subrole)
                    or device_subrole,
                    "device_index": int(device_index),
                }
            }
        )
    else:
        device.update({"parsed_props": None})
    return device



def get_device_tags(device):
    """ Returns a list of all tags a device should have based on hostname """
    device_tags = []
    device = parse_hostname(device)

    # Parsed tags
    if device["parsed_props"]:
        for prop in device["parsed_props"].values():
            if prop in DEVICE_TAGS:
                device_tags.append(prop)

    # Primary & secondary distribution switches
    if "switch-distribution" in device_tags:
        if device["parsed_props"]["device_index"] == 1:
            device_tags.append("primary")
        if device["parsed_props"]["device_index"] == 2:
            device_tags.append("secondary")

    # 3850s often serve dual purposes as access stacks
    if "core-router" in device_tags:
        if '3850' in device['device_type']['model'] or '3750' in device['device_type']['model']:
            device_tags.append("switch-access")
    
    # Sometimes a device's role and subrole will duplicate tags.
    # Casting as set removes duplicates.
    return list(set(device_tags))


def update_device_tags(device):
    """ Updates a device with tags it should have based on hostname """
    device_tags = get_device_tags(device)
    log.debug(f'{device["name"]}: Tags has: {device["tags"]}')
    log.debug(f'{device["name"]}: Tags should have: {device_tags}')
    if device_tags:
        update_tags = []
        for tag in device_tags:
            if tag not in device["tags"]:
                log.info(f'{device["name"]}: Adding tag "{tag}"')
                update_tags.append(tag)
        netbox.dcim.update_device(
            **{
                "device_name": device["name"],
                "tags": update_tags,
            }
        )

def update_all_device_tags(devices):
    return map_threads(update_device_tags, devices)


def main():
    update_all_device_tags(devices)

if __name__ == "__main__":
    main()
