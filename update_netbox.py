import argparse
from concurrent.futures import ThreadPoolExecutor
from netbox import NetBox
import config
import logging
import ipdb
from pprint import pprint
import re


parser = argparse.ArgumentParser()
parser.add_argument(
    "--site",
    "-s",
    help="Site ID to query devices from",
    type=str,
)
parser.add_argument(
    "--tags",
    "-t",
    help="Update device tags based on parsed hostname",
    action="store_true",
)
parser.add_argument(
    "--dry-run",
    "-d",
    help="Print summary of proposed changes without applying them",
    dest="dry_run",
    action="store_true",
)
args = parser.parse_args()


HOSTNAME_PATTERN = r"^(?P<role>\w{1})(?P<site>\w{3})(?P<floor>\d{2})(?P<subrole>\w{2})(?P<index>\d{2})\-?(?P<status>ACT|STB|OLD)?.*$"

# Role is the primary production role of the device
# A device qualifies for role=router if it runs a routing protocol

# Tags are subroles, or properties of roles
NETBOX_TAGS = [
    "access-switch",
    "core-router",
    "distribution-switch",
    "edge-router",
    "primary",
    "secondary",
    "active",
    "standby",
]

HOSTNAME_ROLE_MAP = {
    "O": "wan-accelerator",
    "R": "router",
    "S": "switch",
    "V": "voice-gateway",
    "W": "wireless-controller",
}

HOSTNAME_SUBROLE_MAP = {
    "AC": "access-switch",
    "CR": "core-router",
    "DS": "distribution-switch",
    "ER": "edge-router",  # New, Fulcrum
    "LB": "load-balancer",
    "SS": "server-switch",
    "TS": "console-server",
    "VG": "voice-gateway",
    "WA": "wan-router",  # Legacy
    "WC": "wireless-controller",
    "WO": "wan-accelerator",
}

HOSTNAME_STATUS_MAP = {
    "ACT": "active",
    "STB": "standby",
    "OLD": "legacy",
}

PLATFORM_TAG_MAP = {
    "Network-Arista": "eos",
    "Network-IOS": "ios",
    "Network-IOS-XE": "ios",
    "Network-Juniper": "junos",
    "Network-NXOS": "nxos",
    "Network-Riverbed": "rios",
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
devices = netbox.dcim.get_devices(has_primary_ip=True, site=args.site.upper())
# ipdb.set_trace()


def arg_list(string):
    return string.split(",")


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
        device_status = parsed_hostname.group("status")

        device.update(
            {
                "parsed_props": {
                    "device_role": HOSTNAME_ROLE_MAP.get(device_role)
                    or device_role,
                    "device_site": device_site,
                    "device_floor": int(device_floor),
                    "device_subrole": HOSTNAME_SUBROLE_MAP.get(device_subrole)
                    or device_subrole,
                    "device_index": int(device_index),
                    "device_status": HOSTNAME_STATUS_MAP.get(device_status) or device_status,
                }
            }
        )
    else:
        device.update({"parsed_props": None})
    return device





def get_device_tags(device):
    """Returns a list of all tags a device should have based on hostname"""
    device_tags = []
    device = parse_hostname(device)

    # Parsed tags
    if device["parsed_props"]:
        for prop in device["parsed_props"].values():
            if prop in NETBOX_TAGS:
                device_tags.append(prop)

    # Primary & secondary distribution switches
    if "distribution-switch" in device_tags:
        if device["parsed_props"]["device_index"] == 1:
            device_tags.append("primary")
        if device["parsed_props"]["device_index"] == 2:
            device_tags.append("secondary")

    # 3750/3850s often serve dual purposes as access stacks
    if "core-router" in device_tags:
        if (
            "3850" in device["device_type"]["model"]
            or "3750" in device["device_type"]["model"]
        ):
            device_tags.append("access-switch")

    # Sometimes a device's role and subrole will duplicate tags.
    # Casting as set removes duplicates.
    return list(set(device_tags))


def update_device_tags(device):
    """Updates a device with tags it should have based on hostname"""
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
    if args.dry_run:
        for device in devices:
            tags = get_device_tags(device)
            if tags:
                log.info(f'{device["name"]}: Parsed tags from hostname: {tags}')
            else:
                log.info(f'{device["name"]}: Found no tags in NETBOX_TAGS to apply')
    else:
        update_all_device_tags(devices)


if __name__ == "__main__":
    main()
