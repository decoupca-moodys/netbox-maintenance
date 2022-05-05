import re
from pprint import pprint

import ipdb
from megavolt import MegaVolt

mv = MegaVolt("config.yaml")


class CiscoInterface(object):
    def __init__(self, iface_dict: dict):
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
        for k, v in iface_dict.items():
            setattr(self, f"_{k}", v)

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
            return self.name == 'FastEthernet0' or self.name == 'GigabitEthernet0'

    @property
    def type(self) -> str:
        if self.virtual:
            return "virtual"
        if not self._media_type and 'FastEthernet' in self.name:
            return '100base-t'
        if self._media_type == "10/100-TX":
            return '100base-t'
        if self._media_type == "10/100/1000-TX":
            return "1000base-t"
        if "Ten Gigabit" in self._hardware_type:
            return "10gbase-x-sfpp"

    @property
    def disabled(self) -> bool:
        return (
            "disabled" in self._protocol_status or "admin down" in self._protocol_status
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

    def __repr__(self) -> str:
        return f'<CiscoInterface: {self.name}>'


device = mv.devices.get(name="REDC04CR01")
device.open()
ifaces = device.cli("show interfaces").textfsm_parse_output()
device.close()

# def update_nb_iface(nb_iface, dev_iface: CiscoInterface):
#     nb_iface.enabled = is_enabled(dev_iface)
#     nb_iface.mac = get_mac(dev_iface)
#     nb_iface.mtu = get_mtu(dev_iface)
#     nb_iface.description = get_description(dev_iface)
#     nb_iface.type.value = get_interface_type(dev_iface)

ifaces = [CiscoInterface(x) for x in ifaces]

ipdb.set_trace()
