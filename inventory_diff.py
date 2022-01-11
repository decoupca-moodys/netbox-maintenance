import pandas as pd
import os
from netdev.netbox import netbox
from pprint import pprint

INVENTORY_FILE_PATH = '../connectivity-services/inventory_files'

def parse_inventory_file(contents):
    results = []
    for line in contents:
        split = line.split()
        if len(split) == 1:
            hostname = split[0]
            ip = None
        elif len(split) == 2:
            hostname = split[0]
            ip = split[1]
        else:
            raise ValueError('WTF')
        results.append({
            'hostname': hostname,
            'ip': ip,
        })
    return results

inv_files = os.listdir(os.fsencode(INVENTORY_FILE_PATH))
file_inventory = []
for file in inv_files:
    filepath = '{}/{}'.format(INVENTORY_FILE_PATH, os.fsdecode(file))
    with open(filepath) as fh:
        file_inventory.extend(parse_inventory_file(fh.readlines()))


netbox_inventory = netbox.dcim.get_devices(has_primary_ip=True, limit=0)

for item in netbox_inventory:
    item.update({
        'hostname': item['display'],
        'ip': item['primary_ip4']['address'].split('/')[0]
    })

df1 = pd.DataFrame(file_inventory)
df2 = pd.DataFrame(netbox_inventory)

merge = df1.merge(df2, on='ip', how='outer', indicator=True)

for index, row in merge.iterrows():
    # Hosts from ansible which do not appear in netbox results, when comparing IPs
    # In other words: these records have IPs that do not appear in netbox
    if row['_merge'] == 'left_only':
        hostname = row['hostname_x']
        ip = row['ip']
        # The hostname for this record may appear in netbox under a different IP address, let's check
        lookup_netbox_hostname = [x for x in netbox_inventory if x['hostname'] == hostname]
        if lookup_netbox_hostname:
            print(f'IP mismatch: {hostname} exists in ansible with IP {ip}, but exists in netbox with IP {lookup_netbox_hostname[0]["ip"]}')
        else:
            # Hostname exists in netbox without IP address
            lookup_netbox_hostname = netbox.dcim.get_devices(name=hostname)
            if lookup_netbox_hostname:
                print(f'Missing IP: Hostname {hostname} exists in Netbox but has no IP (should be {ip})')
            else:
                print(f'Not found: Ansible hostname {hostname} and IP {ip} do not exist in Netbox')

import ipdb; ipdb.set_trace()
