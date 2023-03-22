from scapy.all import *
from scapy.layers.dns import DNS, DNSQR, DNSRR
from scapy.layers.inet import IP, UDP

def dnsresponse(packet):
    if packet[DNS].qr == 1:
        print(packet[DNS][DNSRR].rdata)
        return True


dnsrequest = IP(dst="127.0.0.1") / UDP(dport=53) / DNS(rd=1,qd=DNSQR(qname="royandyuval.com"))
send(dnsrequest, verbose=0)
sniff(filter="udp port 53 and dst host 127.0.0.1",stop_filter=lambda p: True, prn=dnsresponse, iface="lo")
