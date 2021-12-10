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
    "--region",
    "-r",
    help="Region ID to query devices from",
    type=str,
)
parser.add_argument(
    "--tag",
    "-t",
    help="Retrieve hosts with tag",
    type=str,
)
parser.add_argument(
    "--list",
    "-l",
    help="List hostnames that match query, do nothing",
    action="store_true",
)
parser.add_argument(
    "--active",
    "-a",
    help="Fetch devices with 'active' status only",
    action="store_true",
)
parser.add_argument(
    "--update-tags",
    "-u",
    help="Update device tags based on properties found in hostname",
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
    "server-switch",
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
log.setLevel(logging.DEBUG)
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
    parsed_props = {
        'role': None,
        'site': None,
        'floor': None,
        'subrole': None,
        'index': None,
        'status': None,
    }
    pattern = re.compile(HOSTNAME_PATTERN)
    parsed_hostname = pattern.search(device["name"])
    if parsed_hostname:
        role = parsed_hostname.group("role")
        site = parsed_hostname.group("site")
        floor = parsed_hostname.group("floor")
        subrole = parsed_hostname.group("subrole")
        index = parsed_hostname.group("index")
        status = parsed_hostname.group("status")
        parsed_props.update({
            "role": HOSTNAME_ROLE_MAP.get(role) or role,
            "site": site,
            "floor": int(floor),
            "subrole": HOSTNAME_SUBROLE_MAP.get(subrole) or subrole,
            "index": int(index),
            "status": HOSTNAME_STATUS_MAP.get(status) or status,
        })
    device.update({"parsed_props": parsed_props, 'tags_should_have': []})
    return device


def get_devices_with_subrole(devices, subrole):
    return [x for x in devices if x['parsed_props']['subrole'] == subrole]

def tag_stp_root_bridges(devices):
    """ Determines which devices of a given list should be STP root  """
    result = {'primary': None, 'secondary': None}
    distribution_switches = get_devices_with_subrole(devices, 'distribution-switch')
    if distribution_switches:
        for device in distribution_switches:
            if device['parsed_props']['index'] == 1:
                device['tags_should_have'].append('stp-root-primary')
                result['primary'] = device
            if device['parsed_props']['index'] == 2:
                device['tags_should_have'].append('stp-root-secondary')
                result['secondary'] = device
    else:
        core_routers = get_devices_with_subrole(devices, 'core-router')
        for device in core_routers:
            if device['parsed_props']['index'] == 1:
                device['tags_should_have'].append('stp-root-primary')
                result['primary'] = device
            if device['parsed_props']['index'] == 2:
                device['tags_should_have'].append('stp-root-secondary')
                result['secondary'] = device
    if result['primary']:
        log.debug(f'{result["primary"]["name"]}: tagged "stp-root-primary"')
    if result['secondary']:
        log.debug(f'{result["secondary"]["name"]}: tagged "stp-root-secondary"')
    return result


def tag_subroles(device):
    """Returns a list of all tags a device should have based on hostname"""
    tags_should_have = device.get('tags_should_have')

    # Parsed tags
    if device["parsed_props"]:
        for prop in device["parsed_props"].values():
            if prop in NETBOX_TAGS:
                tags_should_have.append(prop)

    # Primary & secondary distribution switches / core routers
    if device['parsed_props']['subrole'] == 'distribution-switch' or device['parsed_props']['subrole'] == 'core-router':
        if device["parsed_props"]["index"] == 1:
            tags_should_have.append("primary")
        if device["parsed_props"]["index"] == 2:
            tags_should_have.append("secondary")

    # 3750/3850s often serve dual purposes as access stacks
    if device['parsed_props']['role'] == 'router':
        if (
            "3850" in device["device_type"]["model"]
            or "3750" in device["device_type"]["model"]
        ):
            tags_should_have.append("access-switch")

    # Sometimes a device's role and subrole will duplicate tags.
    # Casting as set removes duplicates.
    tags_should_have = list(set(tags_should_have))
    device.update({'tags_should_have': tags_should_have})
    log.debug(f'{device["name"]}: Tags should have: {tags_should_have}')


def tag_all_subroles(devices):
    for device in devices:
        tag_subroles(device)


def update_device_tags(device):
    """Updates a device with tags it should have """
    #log.debug(f'{device["name"]}: {device["tags_should_have"]}')
    #log.debug(f'{device["name"]}: Updating tags')
    tags_should_have = device.get('tags_should_have')
    #log.debug(f'{device["name"]}: Updating tags')
    if tags_should_have:
        log.debug(f'{device["name"]}: Tags should have: {tags_should_have}')
        tags_has = device['tags']
        tags_has.sort()
        tags_should_have.sort()
        if tags_should_have != tags_has:
            update_tags = [x for x in tags_should_have if x not in tags_has]
            log.info(f'{device["name"]}: Adding tag(s): {update_tags}')
            netbox.dcim.update_device(
                **{
                    "device_name": device["name"],
                    "tags": tags_should_have,
                }
            )
        else:
            log.debug(f'{device["name"]}: Already has all tags it should, nothing to update')
    else:
        log.debug(f'{device["name"]}: Should not have any tags, nothing to update')


def apply_all_device_tags(devices):
    tag_stp_root_bridges(devices)
    tag_all_subroles(devices)

def show_all_device_tags_should_have(devices):
    apply_all_device_tags(devices)
    for device in devices:
        log.info(f'{device["name"]:} Tags needed: {device["tags_should_have"]}')

def update_all_device_tags(devices):
    apply_all_device_tags(devices)
    map_threads(update_device_tags, devices)

def main():
    devices = []
    platforms = netbox.dcim.get_platforms()
    query_args = {'has_primary_ip': True}
    if args.active:
        query_args.update({'status': 'active'})
    if args.tag:
        query_args.update({'tag': args.tag})
    if args.site:
        query_args.update({'site': args.site.upper()})
        devices.extend(netbox.dcim.get_devices(**query_args))
    if args.region:
        log.debug(f'Fetching sites for region "{args.region}"')
        sites = netbox.dcim.get_sites(region=args.region.lower())
        for site in sites:
            log.debug(f'Fetching devices for site "{site["name"]}"')
            query_args.update({'site': site['slug']})
            devices.extend(netbox.dcim.get_devices(**query_args))
            #ipdb.set_trace()

    log.debug(f'Received {len(devices)} devices from NetBox')
    if args.list:
        #pprint(devices[0])
        for device in devices:
            print(device['name'])
    if args.update_tags:
        devices = list(map(parse_hostname, devices))
        apply_all_device_tags(devices)
        log.debug(f'Parsed hostnames into properties')
        if args.dry_run:
            for device in devices:
                if device["tags_should_have"]:
                    log.info(f'{device["name"]}: Should have tags: {device["tags_should_have"]}')
                    log.info(f'{device["name"]}: Has tags: {device["tags"]}')
                else:
                    log.info(f'{device["name"]}: Found no tags to apply')
        else:
            update_all_device_tags(devices)
            #for device in devices:
            #    update_device_tags(device)

if __name__ == "__main__":
    main()
