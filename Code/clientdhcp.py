from scapy.all import *
from scapy.layers.dhcp import DHCP, BOOTP
from scapy.layers.inet import UDP, IP
from scapy.layers.l2 import Ether

clientmac = "00:00:00:00:00:00"

ips = None

def resquest(packet):
    if DHCP in packet and packet[DHCP].options[0][1] == 2:
        requestpacket = Ether(dst="ff:ff:ff:ff:ff:ff", src=clientmac) / \
                              IP(src="0.0.0.0", dst="255.255.255.255") / \
                              UDP(sport=68, dport=67) / \
                              BOOTP(op=1, chaddr=clientmac) / \
                              DHCP(options=[("message-type", "request"), ("requested_addr", packet[BOOTP].yiaddr),("server_id", packet[BOOTP].siaddr), "end"])

        srp1(requestpacket,timeout= 0.5, iface="lo",  verbose=False)
        sniffforack()
    return

def ack(packet):
    if DHCP in packet and packet[DHCP].options[0][1] == 5:
        global ips
        ips = (packet[BOOTP].yiaddr,packet[DHCP].options[2][1])
        return
    else:
        sniffforack()
def sniffforoffer():
    sniff(filter="udp and (port 67 or 68)", stop_filter=lambda p: True, prn=resquest)

def sniffforack():
    sniff(filter="udp and (port 67 or 68)", stop_filter=lambda p: True, prn=ack)

def getip():
    discoverpacket = Ether(dst="ff:ff:ff:ff:ff:ff", src=clientmac) / \
                     IP(src="0.0.0.0", dst="255.255.255.255") / \
                     UDP(sport=68, dport=67) / \
                     BOOTP(op=1, chaddr=clientmac) / \
                     DHCP(options=[("message-type", "discover"), "end"])

    srp1(discoverpacket, timeout=0.5, iface="lo", verbose=False)
    sniffforoffer()
    return ips
if __name__ == '__main__':
    getip()