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

import ipdb; ipdb.set_trace()
