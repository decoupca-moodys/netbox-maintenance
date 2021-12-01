from concurrent.futures import ThreadPoolExecutor
from netbox import NetBox
import config
import logging
import ipdb
from pprint import pprint

root_log = logging.getLogger()
log = logging.getLogger("update_netbox")
log.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(name)s %(levelname)s: %(message)s")
handler.setFormatter(formatter)
root_log.addHandler(handler)

netbox = NetBox(host=config.netbox_host, use_ssl=True, ssl_verify=True, auth_token=config.netbox_token)
platforms = netbox.dcim.get_platforms()
devices = netbox.dcim.get_devices(tag='network-riverbed')
 
tag_map = {
    'Network-Arista': 'eos',
    'Network-IOS': 'ios',
    'Network-IOS-XE': 'ios_xe',
    'Network-Juniper': 'junos',
    'Network-NXOS': 'nxos',
    'Network-Riverbed': 'riverbed',
}

def get_platform_id(platform_slug):
    for platform in platforms:
        if platform['slug'] == platform_slug:
            return platform['id']


def verify_platform(device):
    if device['platform']:
        log.info(f'{device["name"]}: Platform already set, doing nothing')
    else:
        tag = device['tags'][0]
        log.debug(f'{device["name"]}: Tag: "{tag}"')
        platform_slug = tag_map.get(tag)
        log.debug(f'{device["name"]}: Platform slug: "{platform_slug}"')
        if platform_slug:
            platform_id = get_platform_id(platform_slug)
            log.debug(f'{device["name"]}: Platform ID: "{platform_id}"')
            netbox.dcim.update_device_by_id(device_id=device['id'], platform=platform_id)
            log.info(f'{device["name"]}: Updated platform to "{platform_slug}"')
        else:
            log.info(f'{device["name"]}: No platform mapped for tag {tag}, doing nothing')

def verify_all_platforms(devices):
    with ThreadPoolExecutor(max_workers=10) as executor:
        return executor.map(verify_platform, devices)

def main():
    verify_all_platforms(devices)
        
   

if __name__ == '__main__':
    main()

