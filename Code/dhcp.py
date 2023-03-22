from telnetlib import IP

from scapy.all import *
import time

from scapy.layers.dhcp import DHCP, BOOTP
from scapy.layers.inet import UDP
from scapy.layers.l2 import Ether

ipdictionary = {2: 'free', 3: 'free', 4: 'free', 5: 'free', 6: 'free', 7: 'free', 8: 'free', 9: 'free', 10: 'free'}

currentip = None
dnsip = None
dnsrequest = 0
def dhcpserver(packet):
    if DHCP in packet and packet[DHCP].options[0][1] == 1:
        clientmac = packet[Ether].src
        global currentip
        if not currentip:
            currentip = getIpFromPool()
        global dnsrequest
        global dnsip
        if dnsrequest == 0:
            dnsrequest = 1
            dnsip = currentip

        offerpacket = Ether(dst=clientmac)/ \
                        IP(src="100.100.100.254", dst="255.255.255.255")/ \
                        UDP(sport=67, dport=68)/ \
                        BOOTP(op=2, yiaddr=currentip, siaddr="100.100.100.254", chaddr=clientmac) / \
                        DHCP(options=[("message-type", "offer"), ("server_id", "100.100.100.254"), ("name_server", dnsip),
                                      ("subnet_mask", "255.255.255.0"), ("router","100.100.100.1"), ("lease_time", 86400), "end"])

        time.sleep(0.7)
        sendp(offerpacket)
        return

    elif DHCP in packet and packet[DHCP].options[0][1] == 3:
        clientmac = packet[Ether].src
        ackpacket = Ether(dst=clientmac)/ \
                          IP(src="100.100.100.254", dst="255.255.255.255")/ \
                          UDP(sport=67, dport=68)/ \
                          BOOTP(op=2, yiaddr=currentip, siaddr="100.100.100.254", chaddr=clientmac)/ \
                          DHCP(options=[("message-type", "ack"), ("server_id", "100.100.100.254"), ("name_server", dnsip),
                                        ("subnet_mask", "255.255.255.0"), ("router","100.100.100.1"), ("lease_time", 86400), "end"])
        currentip = None
        sendp(ackpacket)

def getIpFromPool():
    for ip in ipdictionary:
        if ipdictionary[ip] == "free":
            ipdictionary[ip] = "occupied"
            return "100.100.100."+str(ip)

if __name__ == '__main__':
    sniff(filter="udp and (port 67 or 68)", prn=dhcpserver, iface="lo")