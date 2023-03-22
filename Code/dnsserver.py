from scapy.all import *
from scapy.layers.dns import DNS, DNSQR, DNSRR
from scapy.layers.inet import IP, UDP
import clientdhcp as dhcp

ipaddres = None

def dnssniffer(packet):
    domain = packet[DNSQR].qname.decode()
    print(f"Received DNS request for {domain}")
    domainstr = str(packet[DNSQR].qname)
    if "royandyuval.com" in domainstr:
        ip = "12.3.20.3"
    else:
        ip = socket.gethostbyname(domain)
    dns_response = DNS(
        id=packet[DNS].id,
        qr=1,
        qd=packet[DNS].qd,
        an=DNSRR(rrname=domain, rdata=ip))
    dnspresponse = IP(dst=packet[IP].src, src=packet[IP].dst) / UDP(dport=packet[UDP].sport,sport=packet[UDP].dport) / dns_response
    send(dnspresponse)


def getipfordns():
    tupleip =dhcp.getip()
    ipaddres = tupleip[0]
    #print(ipaddres)

if __name__ == '__main__':
    getipfordns()
    while True:
        sniff(count=3, filter="udp port 53", prn=dnssniffer, iface="lo")