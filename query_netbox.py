import argparse
from concurrent.futures import ThreadPoolExecutor
from netbox import NetBox
from netmiko import ConnectHandler
import config
import logging
import ipdb
from pprint import pprint
import re
import copy

netmiko_args = {
    "ip": None,
    "username": config.network_username,
    "password": config.network_password,
    "ssh_config_file": "~/.ssh/config",
    "device_type": "cisco_ios",
    "conn_timeout": 30,
    "global_delay_factor": 10,
}

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
    "--include_inactive",
    help="Include inactive records with results",
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
query_args = {"has_primary_ip": True, "status": "active"}
if args.include_inactive:
    del query_args['status']
if args.tag:
    query_args.update({"tag": args.tag})



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
    "ED": "edge-switch",  # Internet-facing edge switch
    "ER": "edge-router",  # New, Fulcrum
    "LB": "load-balancer",
    "MA": "man-router",  # MAN router
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


def parallelize(worker, devices):
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        return executor.map(worker, devices)


def verify_all_platforms(devices):
    return parallelize(verify_platforms, devices)


def is_ios_wlc(device):
    """Determines if an IOS device is also serving as a WLC"""
    wlc_config = "wireless mobility controller"
    if device["platform"]["slug"] != "ios":
        log.debug(f'{device["name"]}: is_ios_wlc: device["platform"]["slug"] != "ios"')
        return False
    else:
        args = copy.deepcopy(netmiko_args)
        args.update({"ip": device["primary_ip4"]["address"].split("/")[0]})
        log.debug(f'{device["name"]}: is_ios_wlc: connecting to device...')
        with ConnectHandler(**args) as conn:
            log.debug(f'{device["name"]}: is_ios_wlc: checking config for wlc_config...')
            cmd = f"show running-config | include wireless"
            output = conn.send_command(cmd)
            if wlc_config in output:
                log.debug(
                    f'{device["name"]}: is_ios_wlc: wlc_config found in running-config'
                )
                return True
            else:
                log.debug(
                    f'{device["name"]}: is_ios_wlc: wlc_config not found in running-config'
                )
                return False


def parse_hostname(device):
    """Parses a hostname into properties dict"""
    parsed_props = {
        "role": None,
        "site": None,
        "floor": None,
        "subrole": None,
        "index": None,
        "status": None,
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
        parsed_props.update(
            {
                "role": HOSTNAME_ROLE_MAP.get(role) or role,
                "site": site,
                "floor": int(floor),
                "subrole": HOSTNAME_SUBROLE_MAP.get(subrole) or subrole,
                "index": int(index),
                "status": HOSTNAME_STATUS_MAP.get(status) or status,
            }
        )
    device.update({"parsed_props": parsed_props, "tags_should_have": []})
    return device


def get_devices_with_subrole(devices, subrole):
    return [x for x in devices if x["parsed_props"]["subrole"] == subrole]


def tag_stp_root_bridges(devices):
    """Determines which devices of a given list should be STP root"""
    result = {"primary": None, "secondary": None}
    distribution_switches = get_devices_with_subrole(devices, "distribution-switch")
    if distribution_switches:
        for device in distribution_switches:
            if device["parsed_props"]["index"] == 1:
                device["tags_should_have"].append("stp-root-primary")
                result["primary"] = device
            if device["parsed_props"]["index"] == 2:
                device["tags_should_have"].append("stp-root-secondary")
                result["secondary"] = device
    else:
        core_routers = get_devices_with_subrole(devices, "core-router")
        for device in core_routers:
            if device["parsed_props"]["index"] == 1:
                device["tags_should_have"].append("stp-root-primary")
                result["primary"] = device
            if device["parsed_props"]["index"] == 2:
                device["tags_should_have"].append("stp-root-secondary")
                result["secondary"] = device
    if result["primary"]:
        log.debug(f'{result["primary"]["name"]}: tagged "stp-root-primary"')
    if result["secondary"]:
        log.debug(f'{result["secondary"]["name"]}: tagged "stp-root-secondary"')
    return result


def tag_subroles(device):
    """Returns a list of all tags a device should have based on hostname"""
    tags_should_have = device.get("tags_should_have")

    # Find core routers that also serve as WLCs
    if device["parsed_props"]["subrole"] == "core-router":
        if is_ios_wlc(device):
            tags_should_have.append("wireless-controller")

    # Parsed tags
    if device["parsed_props"]:
        for prop in device["parsed_props"].values():
            if prop in NETBOX_TAGS:
                tags_should_have.append(prop)

    # Primary & secondary distribution switches / core routers
    if (
        device["parsed_props"]["subrole"] == "distribution-switch"
        or device["parsed_props"]["subrole"] == "core-router"
    ):
        if device["parsed_props"]["index"] == 1:
            tags_should_have.append("primary")
        if device["parsed_props"]["index"] == 2:
            tags_should_have.append("secondary")

    # 3750/3850s often serve dual purposes as access stacks
    if device["parsed_props"]["subrole"] == "edge-router":
        if (
            "3850" in device["device_type"]["model"]
            or "3750" in device["device_type"]["model"]
        ):
            tags_should_have.append("access-switch")

    # Sometimes a device's role and subrole will duplicate tags.
    # Casting as set removes duplicates.
    tags_should_have = list(set(tags_should_have))
    device.update({"tags_should_have": tags_should_have})
    #log.debug(f'{device["name"]}: Tags should have: {tags_should_have}')


def tag_all_subroles(devices):
    parallelize(tag_subroles, devices)

def tag_site_device_subroles(site_result):
    pprint(site_result.items())
    site_slug, devices = site_result.items()
    if devices:
        log.debug(f'{site_slug}: Tagging device subroles')
        tag_all_subroles(devices)

def tag_all_site_device_subroles(site_results):
    log.debug(f'Tagging all site results')
    parallelize(tag_site_device_subroles, site_results)

def has_all_parsed_tags(device):
    has_all_parsed_tags = True
    for tag in device['tags_should_have']:
        if tag not in device['tags']:
            has_all_parsed_tags = False
    return has_all_parsed_tags

def update_device_tags(device):
    """Updates a device with tags it should have.
       Leaves existing tags in place.
    """
    tags_should_have = device.get("tags_should_have")
    if tags_should_have:
        log.debug(f'{device["name"]}: Tags should have based on hostname or config: {tags_should_have}')
        tags_has = device["tags"]
        if not has_all_parsed_tags(device):
            adding_tags = [x for x in tags_should_have if x not in tags_has]
            update_tags = tags_has + adding_tags
            log.info(f'{device["name"]}: Adding tag(s): {adding_tags}')
            netbox.dcim.update_device(
                **{
                    "device_name": device["name"],
                    "tags": update_tags,
                }
            )
        else:
            log.debug(
                f'{device["name"]}: Already has all tags it should, nothing to update'
            )
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
    parallelize(update_device_tags, devices)

def get_site(site_name):
    return netbox.dcim.get_sites(name=site_name.upper())

def get_devices_from_site(site):
    log.debug(f'Getting devices from site {site["name"]}')
    site_args = copy.deepcopy(query_args)
    site_args.update({"site": site["slug"]})
    devices = netbox.dcim.get_devices(**site_args)
    return {site["slug"]: devices}

def get_devices_from_sites(sites):
    return parallelize(get_devices_from_site, sites)

def get_sites_from_region(region):
    log.debug(f'Getting sites for region "{region}"')
    return netbox.dcim.get_sites(region=region.lower())

def get_devices_from_region(region):
    log.debug(f'Getting devices for region "{region}"')
    sites = get_sites_from_region(region)
    return get_devices_from_sites(sites)

def get_tags_needed(device):
    tags_has = device['tags']
    tags_needed = device['tags_should_have']
    return [x for x in tags_should_have if x not in tags_has]

def tags_to_string(tags):
    output = ''
    for tag in tags:
        output += f'"{tag}", '
    return output[:-2]

def main():
    #platforms = netbox.dcim.get_platforms()
    result_list = [] 
    if args.site:
        site = get_site(args.site)
        site_results = [get_devices_from_site(site[0])]
    if args.region:
        site_results = get_devices_from_region(args.region)
    for site_result in site_results:
        for site_slug, devices in site_result.items():
            if args.list:
                for device in devices:
                    print(device['name'])
            devices = list(map(parse_hostname, devices))
            # Must be done per site
            tag_stp_root_bridges(devices)
        result_list.append({site_slug: devices})
    tag_all_site_device_subroles(result_list)
    if args.update_tags:
        if args.dry_run:
            for device in devices:
                if device['tags_should_have']:
                    if has_all_parsed_tags(device):
                        log.info(f'{device["name"]}: No tags to update - already has all parsed tags')
                        log.info(f'{device["name"]}: Has tags: {tags_to_string(device["tags"])}')
                        log.info(f'{device["name"]}: Parsed tags: {tags_to_string(device["tags_should_have"])}')

                    else:
                        tags_needed = get_tags_needed(device)
                        log.info(f'{device["name"]}: Needs tags: {tags_to_string(tags_needed)}')
                else:
                    log.info(f'{device["name"]}: No tags to update - found no parsed tags to apply')
        else:
            update_all_device_tags(devices)
            # for device in devices:
            #    update_device_tags(device)


if __name__ == "__main__":
    main()
