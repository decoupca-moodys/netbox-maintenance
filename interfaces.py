import re
from pprint import pprint
from typing import Union

import ipdb
from megavolt import MegaVolt

mv = MegaVolt("config.yaml")


EXCLUDE_VLANS = [
    1,
    1002,
    1003,
    1004,
    1005,
]

class IOSInterface(object):
    def __init__(self, sh_int: dict, iface_config = None):
        self._abort = None
        self._address = None
        self._bandwidth = None
        self._bia = None
        self._crc = None
        self._delay = None
        self._description = None
        self._duplex = None
        self._encapsulation = None
        self._hardware_type = None
        self._input_errors = None
        self._input_packets = None
        self._input_rate = None
        self._interface = None
        self._ip_address = None
        self._last_input = None
        self._last_output = None
        self._last_output_hang = None
        self._link_status = None
        self._media_type = None
        self._mtu = None
        self._output_errors = None
        self._output_packets = None
        self._output_rate = None
        self._protocol_status = None
        self._queue_strategy = None
        self._speed = None
        for k, v in sh_int.items():
            setattr(self, f"_{k}", v)
        self._config = iface_config or {}

    @property
    def name(self) -> str:
        return self._interface.strip()

    @property
    def physical(self) -> bool:
        if "management" in self._hardware_type:
            return True
        else:
            return "N/A" not in self._media_type and bool(self._media_type)

    @property
    def virtual(self) -> bool:
        return not self.physical

    @property
    def management(self) -> bool:
        if 'management' in self._hardware_type:
            return True
        else:
            # TODO: this may not be a safe bet
            return self.physical is True and '/' not in self.name

    @property
    def type(self) -> str:
        if self.virtual:
            return "virtual"
        if not self._media_type and 'FastEthernet' in self.name:
            return '100base-tx'
        if self._media_type == "10/100-TX":
            return '100base-tx'
        if self._media_type == "10/100/1000-TX":
            return "1000base-t"
        if "Ten Gigabit" in self._hardware_type:
            return "10gbase-x-sfpp"

    @property
    def disabled(self) -> bool:
        return (
            "disabled" in self._protocol_status.lower() or "administratively down" in self._link_status.lower()
        )

    @property
    def enabled(self) -> bool:
        return not self.disabled

    @property
    def mtu(self) -> int:
        if self._mtu:
            return int(self._mtu) or None

    @property
    def mac(self) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", self._address) or None

    @property
    def description(self) -> str:
        return self._description.strip() or None

    @property
    def ip(self) -> str:
        return self._ip_address or None

    @property
    def vrf(self) -> Union[str, None]:
        return self._config.get('vrf')

    @property
    def untagged_vlan(self) -> Union[int, None]:
        mode = self._config.get('switchport_mode')
        if mode == 'access' or mode is None:
            return self._config.get('switchport_access_vlan')
        if mode == 'trunk':
            return self._config.get('switchport_trunk_native_vlan')
        
    @property
    def tagged_vlans(self) -> Union[list, None]:
        mode = self._config.get('switchport_mode')
        if mode == 'trunk':
            return self._config.get('switchport_trunk_allowed_vlans')
        else:
            return None

    @property
    def svi(self) -> bool:
        return 'vlan' in self.name.lower()

    @property
    def loopback(self) -> bool:
        return 'loopback' in self.name.lower()
    
    @property
    def lag(self) -> bool:
        return 'port-channel' in self.name.lower()

    @property
    def mode(self) -> Union[str, None]:
        """
        802.1q mode
        """
        allowed_vlans = self._config.get('switchport_trunk_allowed_vlans')
        switchport_enabled = self._config.get('switchport_enabled')
        mode = self._config.get('switchport_mode')
        if self.management is True:
            return None
        # only physical switchportst or portchannels can have 802.1q modes
        if self.physical is True or self.lag is True:
            if switchport_enabled is False:
                return None
            else:
                # ports default to access mode
                if mode == 'access' or mode is None:
                    return 'access'
                elif mode == 'trunk':
                    # trunks default to allow all vlan tags
                    if allowed_vlans is None:
                        return 'tagged-all'
                    else:
                        return 'tagged'
        else:
            return None


    def __repr__(self) -> str:
        return self.name
    
    def __str__(self) -> str:
        return self.name


class IOSVlan(object):
    def __init__(self, sh_vlan):
        self._name = None
        self._vlan_id = None
        self._status = None
        self._interfaces = None
        for k, v in sh_vlan.items():
            setattr(self, f'_{k}', v)
    
    @property
    def name(self):
        return self._name or None

    @property
    def vid(self):
        return int(self._vlan_id) or None

    @property
    def id(self):
        return self.vid or None
    
    @property
    def interfaces(self):
        return self._interfaces or []

    @property
    def status(self):
        if 'act' in self._status.lower():
            return 'active'

        

device = mv.devices.get(name="RBEH00CR01")
device.open()
dev_ifaces = device.cli("show interfaces").textfsm_parse_output()
sh_run = device.cli('show run')
dev_vlans = device.cli('show vlan').textfsm_parse_output()
device.close()

# def update_nb_iface(nb_iface, dev_iface: CiscoInterface):
#     nb_iface.enabled = is_enabled(dev_iface)
#     nb_iface.mac = get_mac(dev_iface)
#     nb_iface.mtu = get_mtu(dev_iface)
#     nb_iface.description = get_description(dev_iface)
#     nb_iface.type.value = get_interface_type(dev_iface)

parsed_config = sh_run.ttp_parse_output('show_running-config.ttp')[0]
dev_ifaces = [IOSInterface(iface, parsed_config['interfaces'].get(iface['interface'])) for iface in dev_ifaces]
dev_vlans = [IOSVlan(vlan) for vlan in dev_vlans]
nb_ifaces = mv.interfaces.filter(device_id=device.nb.id)
nb_vlans = [x for x in mv.nb.ipam.vlans.filter(site=device.nb.site.slug)]

def _format_mac(mac) -> str:
    mac = mac.upper()
    return ':'.join(mac[i:i+2] for i in range(0,12,2))

def _get_nb_vlan(vid, nb_vlans=nb_vlans):
    for nb_vlan in nb_vlans:
        if nb_vlan.vid == vid:
            return nb_vlan.id

def nb_iface_exists(nb_ifaces, iface_name) -> bool:
    for nb_iface in nb_ifaces:
        if nb_iface.name == iface_name:
            return True
    return False

def nb_vlan_exists(vid, nb_vlans=nb_vlans) -> bool:
    for nb_vlan in nb_vlans:
        if nb_vlan.vid == vid:
            return True
    return False

def _get_dev_iface(name, dev_ifaces=dev_ifaces):
    for dev_iface in dev_ifaces:
        if dev_iface.name == name:
            return dev_iface

def _get_nb_iface_dict(name):
    dev_iface = _get_dev_iface(name)
    iface_dict = {
        'device': device.nb.id,
        'name': dev_iface.name,
        'type': dev_iface.type,
        'enabled': dev_iface.enabled,
        'mgmt_only': dev_iface.management,
        'mtu': dev_iface.mtu,
        'mac_address': _format_mac(dev_iface.mac) if dev_iface.mac is not None else None,
        'description': dev_iface.description or '',
        'mode': dev_iface.mode,
        'untagged_vlan': _get_nb_vlan(dev_iface.untagged_vlan),
    }
    if dev_iface.tagged_vlans is not None:
        iface_dict.update({
            'tagged_vlans': [_get_nb_vlan(int(vid)) for vid in dev_iface.tagged_vlans if _get_nb_vlan(int(vid))],
        })
    else:
        iface_dict.update({
            'tagged_vlans': [],
        })
    return iface_dict

def _get_nb_vlan_dict(vid):
    dev_vlan = _get_dev_vlan(vid)
    if dev_vlan is not None:
        return {
            'name': dev_vlan.name,
            'vid': dev_vlan.vid,
            'status': dev_vlan.status,
            'site': device.nb.site.id,
        }

def get_nb_ifaces_to_create(nb_ifaces, dev_ifaces) -> list:
    create = []
    for dev_iface in dev_ifaces:
        if not nb_iface_exists(nb_ifaces, dev_iface.name):
            create.append(_get_nb_iface_dict(dev_iface.name))
    return create

def get_nb_vlans_to_create(nb_vlans, dev_vlans):
    create = []
    for dev_vlan in dev_vlans:
        if dev_vlan.vid not in EXCLUDE_VLANS:
            if not nb_vlan_exists(dev_vlan.vid):
                create.append(_get_nb_vlan_dict(dev_vlan.vid))
    return create

def get_nb_ifaces_to_delete(nb_ifaces, dev_ifaces):
    delete = []
    for nb_iface in nb_ifaces:
        if not nb_iface_exists(dev_ifaces, nb_iface.name):
            delete.append(nb_iface)
    return delete

def get_nb_ifaces_to_update(nb_ifaces):
    updates = []
    for nb_iface in nb_ifaces:
        nb_dict = _get_nb_iface_dict(nb_iface.name)
        for key, new_value in nb_dict.items():
            setattr(nb_iface, key, new_value)
        if nb_iface._diff():
            updates.append(nb_iface)
    return updates

def _get_dev_vlan(vid, dev_vlans=dev_vlans):
    for dev_vlan in dev_vlans:
        if dev_vlan.vid == vid:
            return dev_vlan



def get_nb_vlans_to_update(nb_vlans):
    updates = []
    for nb_vlan in nb_vlans:
        if nb_vlan.vid not in EXCLUDE_VLANS:
            nb_dict = _get_nb_vlan_dict(nb_vlan.vid)
            if nb_dict is not None:
                for key, new_value in nb_dict.items():
                    setattr(nb_vlan, key, new_value)
                if nb_vlan._diff():
                    updates.append(nb_vlan)
    return updates

vlan_create = get_nb_vlans_to_create(nb_vlans, dev_vlans)
vlan_updates = get_nb_vlans_to_update(nb_vlans)

iface_create = get_nb_ifaces_to_create(nb_ifaces, dev_ifaces)
iface_delete = get_nb_ifaces_to_delete(nb_ifaces, dev_ifaces)
iface_updates = get_nb_ifaces_to_update(nb_ifaces)

if vlan_create:
    ipdb.set_trace()
    mv.nb.ipam.vlans.create(vlan_create)
if vlan_updates:
    ipdb.set_trace()
    mv.nb.ipam.vlans.update(vlan_updates)
if iface_create:
    ipdb.set_trace()
    mv.nb.dcim.interfaces.create(iface_create)
if iface_updates:
    ipdb.set_trace()
    mv.nb.dcim.interfaces.update(iface_updates)
if iface_delete:
    ipdb.set_trace()
    mv.nb.dcim.interfaces.delete(iface_delete)
ipdb.set_trace()
