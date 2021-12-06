from concurrent.futures import ThreadPoolExecutor
from netbox import NetBox
import config
import logging
import ipdb
from pprint import pprint
import re


HOSTNAME_PATTERN = r"^(?P<role>\w{1})(?P<site>\w{3})(?P<floor>\d{2})(?P<subrole>\w{2})(?P<index>\d{2})$"

DEVICE_TAGS = {
    "switch-access": "Switch - Access",
    "switch-distribution": "Switch - Distribution",
    "primary": "Primary",
    "secondary": "Secondary",
    "layer2": "Layer 2",
    "layer3": "Layer 3",
    "edge-router": "Edge Router",
}

HOSTNAME_ROLE_TAG_MAP = {
    "R": "router",
    "S": "switch",
    "W": "wireless-controller",
    "V": "voice-gateway",
    "O": "wan-accelerator",
}

HOSTNAME_SUBROLE_TAG_MAP = {
    "AC": "switch-access",
    "DS": "switch-distribution",
    "SS": "switch-server",
    "VG": "voice-gateway",
    "WC": "wireless-controller",
    "TS": "console-server",
    "LB": "load-balancer",
    "WA": "wan-router",  # Legacy
    "ER": "edge-router",  # New, Fulcrum
    "CR": "core-router",
    "WO": "wan-accelerator",
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
devices = netbox.dcim.get_devices(has_primary_ip=True, site="WTC")


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


def verify_tags_created(netbox):
    existing_tags = netbox.extras.get_tags()
    for desired_tag in DEVICE_TAGS.items():
        tag_args = {"slug": desired_tag.key, "name": desired_tag.value}
        for existing_tag in existing_tags:
            if existing_tag["slug"] == desired_tag.key:
                tag_exists = True
        if tag_exists:
            log.info(f'Tag {desired_tag["name"]} exists, updating.')
            update = {"slug": desired_tag["slug"]}
            netbox.extras.update_tag(**tag_args)
        else:
            log.info(f'Creating tag: {desired_tag["name"]}')
            netbox.extras.create_tag(**tag_args)


def update_device_tags(device):
    device_tags = []
    device = parse_hostname(device)

    # Parsed tags
    if device["parsed_props"]:
        for prop in device["parsed_props"].values():
            if prop in DEVICE_TAGS.keys():
                device_tags.append(prop)

    # Primary & secondary distribution switches
    if "switch-distribution" in device_tags:
        if device["parsed_props"]["device_index"] == 1:
            device_tags.append("primary")
        if device["parsed_props"]["device_index"] == 2:
            device_tags.append("secondary")

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


def verify_all_tags(device):
    pass


def main():
    for device in devices:
        # device = parse_hostname(device)

        # print(device['name'])
        # pprint(device['parsed_props'])
        update_device_tags(device)


if __name__ == "__main__":
    main()
