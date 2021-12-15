import argparse
import config
from netbox import NetBox
from pprint import pprint

parser = argparse.ArgumentParser()
parser.add_argument('--site', '-s', help="Site to query", type=str)
parser.add_argument('--region', '-r', help="Region to query", type=str)
args = parser.parse_args()

netbox = NetBox(**config.netbox_args)

def get_sites_in_region(region):
    """Gets all sites for a given region"""
    return netbox.dcim.get_sites(region=region.lower())

def get_site(site_string):
    """Resolves a site string (slug) to a site object"""
    return netbox.dcim.get_sites(name=site_string.upper())

def get_site_circuits(site):
    """Gets all circuits for a given site"""
    circuits = netbox.circuits.get_circuits(site=site["slug"])
    circuits = [x for x in circuits if x]
    return circuits

def get_side_z_report(circuits):
    for circuit in circuits:
        z_side = circuit.get('termination_z')
        if z_side:
            name = z_side['site']['name']
            slug = z_side['site']['slug']
            z_side_site = get_site(slug)[0]
            print(f' --> {z_side_site["name"]} - {z_side_site["facility"]} ')

def get_site_circuit_report(sites):
    for site in sites:
        circuits = get_site_circuits(site)
        if circuits:
            print(f'{site["name"]} - {site["facility"]}')
            get_side_z_report(circuits)

def main():
    if args.site:
        sites = get_site(args.site)
    if args.region:
        sites = get_sites_in_region(args.region)
    get_site_circuit_report(sites)
    #pprint(get_site_circuits(sites[0]))

if __name__ == '__main__':
    main()
