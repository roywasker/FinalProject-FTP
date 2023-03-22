import socket
import threading
import time
# from utils import log


def log(msg):
    return


# maximum transmission unit, the max size of a packet
MTU = 1024

# packet header length (12 Bytes)
HEADER_LENGTH = 12

# maximum seconds the socket can be idle before an exception is raised
SOCKET_MAX_TIMEOUT = 60

# if max packet loss reached (the number of packets waiting for acknowledge)
# then wait this number of seconds between packet-send retry
SLEEP_BETWEEN_RETRIES = 0.05 # 50 ms

# number of maximum retries to send a packet, if this number is reached, then rais exception
MAX_SEND_RETRIES = 600 # 30 seconds

# maximum window size (max simultaneously send packets)
MAX_WINDOW_SIZE = 10

# RUDP packet type SYN for synchronisation between sender and receiver
PACKET_TYPE_SYN = 0

# RUDP packet type DATA for transferring data between sender and receiver
PACKET_TYPE_DATA = 1

# RUDP packet type ACK for acknowledging DATA packet received by other side
PACKET_TYPE_ACK = 2

# RUDP packet type END for signaling that the current data buffers are all sent
PACKET_TYPE_END = 3

# RUDP packet type RST for signaling end of communication between sender and receiver
PACKET_TYPE_RST = 4


def parsePacket(receivedPacket):
    # get the first 4 bytes and convert them into int, this will be the received packetType
    receivedPacketType = int.from_bytes(receivedPacket[0:4], 'big')

    # get the next 4 bytes and convert them into int, this will be the received sequenceNumber
    receivedSequenceNumber = int.from_bytes(receivedPacket[4:8], 'big')

    # get the next 4 bytes and convert them into int, this will be the received dataLength
    receivedDataLength = int.from_bytes(receivedPacket[8:HEADER_LENGTH], 'big')

    # get the last bytes from end of header, read up to receivedDataLength and set it as received data
    receivedData = receivedPacket[HEADER_LENGTH:HEADER_LENGTH + receivedDataLength]

    return receivedPacketType, receivedSequenceNumber, receivedDataLength, receivedData


class RUDPSocket:
    # a flag that indicates if the socket is opened and connected and has finished the handshake (sent & received SYN)
    isConnected = False

    # flag indicating connection is closed
    isClosed = False

    # an event that indicates the socket has connected and is open
    isConnectedEvent = threading.Event()

    # a buffer that accumulate the DATA packets in correct order into a full byte data buffer
    receivedDataBuffer = b''

    # a flag that indicates if a data was read from the socket and is ready to be consumed by the caller
    isDataReady = False

    # an event that indicates the data is ready for read by the caller
    isDataReadyEvent = threading.Event()

    # the udp socket we open to the receiver side as senders, or as a receiver for listening
    rudpSocket = None

    # the ipv4 address and port of the receiver side on this socket
    receiverAddress = None

    # the ipv4 address and port of this side on the socket
    selfAddress = None

    # a sequence number that is incremented each time a packet is sent (the max sequence is 65,535 [FFFF])
    sequenceNumber = 0

    # thread lock to use when changing the sequenceNumber member
    sequenceNumberLock = threading.Lock()

    # a member that holds the RUDP window size (max simultaneous sent packets)
    windowSize = 1

    # thread lock to use when changing the windowSize member
    windowSizeLock = threading.Lock()

    # dictionary that holds all the sequence numbers and packets that were not acknowledge yet
    waitingForAcknowledge = {}

    # thread lock to use when changing the waitingForAcknowledge member
    waitingForAcknowledgeLock = threading.Lock()


    # -------------------------------------------------------------------------------------------- #
    # open RUDP socket for sending, send SYN packet, wait for SYN reply & mark socket as connected #
    # -------------------------------------------------------------------------------------------- #
    def connect(self, address):
        # save the address we are connecting to (the other side address)
        self.receiverAddress = address

        # create a UDP socket, and send SYN to receiver
        self.rudpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rudpSocket.settimeout(SOCKET_MAX_TIMEOUT)
        self.sendSynPacket()

        # launch a thread that listen to received control packets (ACK/SYN/END messages)
        listenerThread = threading.Thread(target=self.handleControlPackets)
        listenerThread.start()

        # launch thread that retransmission waiting for ACK packets
        retransmissionThread = threading.Thread(target=self.retransmitWaitingPackets)
        retransmissionThread.start()


    # ------------------------------------------------------------------------- #
    # alias function that closes the socket and marking the socket as closed so #
    # the send/receive threads will quit                                        #
    # ------------------------------------------------------------------------- #
    def close(self):
        if self.isConnected:
            self.sendRSTPacket()
        # mark sender socket as closed
        self.isConnected = False
        self.isClosed = True
        # close the udp socket
        self.rudpSocket.close()


    # ------------------------------------------------------------------------------ #
    # alias function that sends bytes data to the receiver using the RUDP protocol   #
    # send DATA packets with sequenceNumbers and expects ACK packets to return with #
    # the same sequenceNumber for each packet and once all the data packets were     #
    # sent it will send a final RST packet                                           #
    # ------------------------------------------------------------------------------ #
    def send(self, dataToSend):
        # make sure the socket is connected (SYN has been sent and received)
        if not self.isConnected:
            self.isConnectedEvent.wait(SLEEP_BETWEEN_RETRIES * MAX_SEND_RETRIES)

        # slice the data into smaller chunks at MTU size
        # calculate what is the total bytes we are about to send in this packet
        totalBytesToSend = len(dataToSend)
        # reset the total sent bytes counter
        totalBytesSent = 0
        # loop until there is nothing left to send
        while totalBytesSent < totalBytesToSend:
            # get the next chunk of bytes in the MTU size from the data to send
            nextDataChunkToSend = dataToSend[totalBytesSent:MTU]

            # if we reached the maximum number of lost packets waiting for acknowledge
            # then wait until one of them succeed before you send the next packet
            numberOfRetries = 0
            while len(self.waitingForAcknowledge) >= self.windowSize:
                if numberOfRetries >= MAX_SEND_RETRIES:
                    # clear the waiting for ack dictionary so next send will start fresh
                    with self.waitingForAcknowledgeLock:
                        self.waitingForAcknowledge.clear()
                        raise Exception('Failed to send data, not all packets got ACKs')
                numberOfRetries = numberOfRetries + 1
                time.sleep(SLEEP_BETWEEN_RETRIES)

            # if we had to wait for ack to return then reduce the window size so fewer packets are lost
            if numberOfRetries > 0:
                self.reduceWindowSize()

            # send the current data chunk
            self.sendDataPacket(nextDataChunkToSend)
            # add another chunk size to the totalBytesSent counter
            totalBytesSent = totalBytesSent + MTU

        # after all packets are sent, send the END packet
        self.sendENDPacket()

        # wait for all ACK packets to return or rais exception after timeout has reached
        numberOfRetries = 0
        while len(self.waitingForAcknowledge) > 0:
            if numberOfRetries >= MAX_SEND_RETRIES:
                # clear the waiting for ack dictionary so next send will start fresh
                with self.waitingForAcknowledgeLock:
                    self.waitingForAcknowledge.clear()
                    raise Exception(f"Failed to receive ACK packets for all the sent packets: {self.waitingForAcknowledge}")
            numberOfRetries = numberOfRetries + 1
            time.sleep(SLEEP_BETWEEN_RETRIES)


    # ------------------------------------------------------------ #
    # sets the socket max timeout for connect/send/receive actions #
    # ------------------------------------------------------------ #
    def setTimeout(self, socketMaxTimeout):
        self.rudpSocket.settimeout(socketMaxTimeout)


    # --------------------------------------- #
    # receives bytes data from sender clients #
    # --------------------------------------- #
    def receive(self, maxBufferSize):
        if not self.isClosed:
            # wait for socket to connect
            if not self.isConnected:
                self.isConnectedEvent.wait(SLEEP_BETWEEN_RETRIES * MAX_SEND_RETRIES)

            # wait for data to be ready and return it
            if not self.isDataReady:
                self.isDataReadyEvent.wait(SLEEP_BETWEEN_RETRIES * MAX_SEND_RETRIES)
                self.isDataReadyEvent.clear()

            result = self.receivedDataBuffer
            self.receivedDataBuffer = b''
            self.isDataReady = False

            return result


    # --------------------------------------------------------- #
    # open RUDP socket for receiving, binds socket to ip & port #
    # --------------------------------------------------------- #
    def listen(self, address):
        # open a UDP socket and bind it to host & port
        self.rudpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rudpSocket.settimeout(SOCKET_MAX_TIMEOUT)
        self.rudpSocket.bind(address)


    # --------------------------------------------------------------------- #
    # wait for incoming connections, once a connection is accepted, it will #
    # return the connected client socket and client address (ip & port)     #
    # --------------------------------------------------------------------- #
    def accept(self):
        # wait & accept incoming connections
        # ask udp socket to receive data in the Max Transmission Unit size
        receivedPacket, clientAddress = self.rudpSocket.recvfrom(MTU)

        # create a new RUDPSocket
        clientRUDPSocket = RUDPSocket()
        # connect to the client with the newly created socket
        clientRUDPSocket.connect(clientAddress)
        # return the new RUDPSocket to the caller
        return clientRUDPSocket


    def retransmitWaitingPackets(self):
        while True:
            # if socket has been closed - stop retransmitWaitingPackets thread from working
            if self.isClosed:
                break
            log(f"retransmitWaitingPackets() {self.waitingForAcknowledge}")
            with self.waitingForAcknowledgeLock:
                for currentSequenceNumer, currentPacket in self.waitingForAcknowledge.items():
                    # log(f"retransmitWaitingPackets(): {currentPacket} to: {self.receiverAddress}")
                    self.rudpSocket.sendto(currentPacket, self.receiverAddress)
            time.sleep(7)


    # --------------------------------------- #
    # receives bytes data from sender clients #
    # --------------------------------------- #
    def handleControlPackets(self):
        # calculate the maximum number of expected packets, by calculating: maxBufferLength : (packetSize - headerSize)
        numberOfExpectedPackets = 5000 / (MTU - HEADER_LENGTH)
        # prepare a byte array to store all the received data packets
        receivedDataArray = [b''] * round(numberOfExpectedPackets)
        firstPacketSequenceNumber = 0
        while True:
            # if socket has been closed - stop handleControlPackets thread from working
            if self.isClosed:
                break
            # read until there is nothing to read
            try:
                # peak at the buffer and check if the next message is sent by client or ourselves
                peekedData, peekedAddress = self.rudpSocket.recvfrom(MTU, socket.MSG_PEEK)
                if peekedAddress != self.selfAddress:
                    # read bytes from the socket
                    receivedPacket, clientAddress = self.rudpSocket.recvfrom(MTU)
                    log(f"receive(): {receivedPacket} from: {clientAddress}")
                    if receivedPacket and clientAddress != self.selfAddress:
                        # save the sender ip and port as the receiver address (so initiator port (8080) will be abandon)
                        self.receiverAddress = clientAddress
                        # parse the received packet
                        receivedPacketType, receivedSequenceNumber, receivedDataLength, receivedData = parsePacket(receivedPacket)
                        if receivedPacketType == PACKET_TYPE_SYN:
                            log("receive(): Got SYN packet")
                            # received SYN packet from sender, mark socket as connected & reply with ACK with SYN SequenceNumber
                            # save the expected first packet sequence number, it will be used later
                            # to calculate each arriving data packet place in the receivedDataArray
                            firstPacketSequenceNumber = receivedSequenceNumber + 1
                            self.sendAckPacket(receivedSequenceNumber)
                            # sleep for 100 milliseconds to allow other side to consume the sent message
                            time.sleep(0.1)
                        elif receivedPacketType == PACKET_TYPE_DATA:
                            log(f"handleSenderControlPackets(): Got DATA packet, receivedSequenceNumber: {receivedSequenceNumber} firstPacketSequenceNumber: {firstPacketSequenceNumber}")
                            if not self.isDataReady:
                                # received DATA packet from the sender add to total data buffer (in correct order) & return ACK
                                receivedDataArray[receivedSequenceNumber - firstPacketSequenceNumber] = receivedData
                                self.sendAckPacket(receivedSequenceNumber)
                        elif receivedPacketType == PACKET_TYPE_ACK:
                            log("handleSenderControlPackets(): Got ACK packet")
                            # if ACK packet received from the receiver then remove the received SequenceNumber from the waitingForAcknowledge
                            with self.waitingForAcknowledgeLock:
                                if len(self.waitingForAcknowledge) > 0:
                                    poppedPacket = self.waitingForAcknowledge.pop(receivedSequenceNumber)
                                    if poppedPacket:
                                        # increase the window size (since we succeeded)
                                        self.increaseWindowSize()
                                        # if we received an ACK for the SYN then mark socket as connected
                                        poppedPacketType, poppedSequenceNumber, poppedDataLength, poppedData = parsePacket(poppedPacket)
                                        if poppedPacketType == PACKET_TYPE_SYN:
                                            self.isConnected = True
                                            self.isConnectedEvent.set()
                                            log("SYN ACK received")
                        elif receivedPacketType == PACKET_TYPE_END:
                            # received END packet that means the current data buffer transmission ended,
                            # next packets belongs to the next data buffer, return data buffer to caller
                            log("handleSenderControlPackets(): Got END packet")
                            self.receivedDataBuffer = b''.join(receivedDataArray)
                            receivedDataArray = [b''] * round(numberOfExpectedPackets)
                            firstPacketSequenceNumber = receivedSequenceNumber + 1
                            self.isDataReady = True
                            self.isDataReadyEvent.set()
                        elif receivedPacketType == PACKET_TYPE_RST:
                            # received RST packet from sender, close the socket
                            log("handleSenderControlPackets(): Got RST packet")
                            self.isConnected = False
                            self.close()
                            break
                        else:
                            # if we received any other packet type then print error message
                            log(f"handleSenderControlPackets(): unexpected packet type: {receivedPacketType}, ignoring it")
            except Exception as err:
                # error occurred, maybe socket was cosed by caller, break from loop
                if "timed out" not in str(err):
                    if 'forcibly closed' not in str(err):
                        log("Warning some problem occurred while trying to receive data from socket: " + str(err))
                    else:
                        # other side closed the socket, close this side too
                        self.close()
                        break


    def getNextSequenceNumber(self):
        # acquire the sequence number lock so only this thread can change the sequence number value
        with self.sequenceNumberLock:
            if self.sequenceNumber < 65535:
                # increase the sequence number by 1
                self.sequenceNumber = self.sequenceNumber + 1
            else:
                # reset the sequence number back to 0 since it is about to exceed the 4 byte max number (FFFF)
                self.sequenceNumber = 0
            return self.sequenceNumber


    def reduceWindowSize(self):
        with self.windowSizeLock:
            if self.windowSize > 1:
                self.windowSize = self.windowSize - 1


    def increaseWindowSize(self):
        with self.windowSizeLock:
            if self.windowSize < MAX_WINDOW_SIZE:
                self.windowSize = self.windowSize + 1


    def sendSynPacket(self):
        log("sendSynPacket()")
        # get the next valid sequence number, send the packet and add it to waiting for acknowledge dictionary
        sequenceNumber = self.getNextSequenceNumber()
        rudpPacket = self.sendRUDPPacket(PACKET_TYPE_SYN, sequenceNumber, bytes("", "utf-8"))
        with self.waitingForAcknowledgeLock:
            self.waitingForAcknowledge[sequenceNumber] = rudpPacket


    def sendDataPacket(self, dataToSend):
        log("sendDataPacket()")
        # get the next valid sequence number, send the packet and add it to waiting for acknowledge dictionary
        sequenceNumber = self.getNextSequenceNumber()
        rudpPacket = self.sendRUDPPacket(PACKET_TYPE_DATA, sequenceNumber, dataToSend)
        with self.waitingForAcknowledgeLock:
            self.waitingForAcknowledge[sequenceNumber] = rudpPacket


    def sendENDPacket(self):
        log("sendENDPacket()")
        # get the next valid sequence number
        sequenceNumber = self.getNextSequenceNumber()
        self.sendRUDPPacket(PACKET_TYPE_END, sequenceNumber, bytes("", "utf-8"))


    def sendRSTPacket(self):
        log("sendRSTPacket()")
        # get the next valid sequence number
        sequenceNumber = self.getNextSequenceNumber()
        self.sendRUDPPacket(PACKET_TYPE_RST, sequenceNumber, bytes("", "utf-8"))


    def sendAckPacket(self, sequenceNumberToAck):
        log("sendAckPacket()")
        self.sendRUDPPacket(PACKET_TYPE_ACK, sequenceNumberToAck, bytes("", "utf-8"))


    def sendRUDPPacket(self, packetType, packetSequenceNumber, packetData):
        # set the value of the packet header fields
        packetDataLength = len(packetData)  # payload length, the length of the data bytes

        # convert the packet header fields into 4 bytes, in big-endian order
        packetTypeBytes = packetType.to_bytes(4, byteorder='big')
        packetSequenceNumberBytes = packetSequenceNumber.to_bytes(4, byteorder='big')
        packetDataLengthBytes = packetDataLength.to_bytes(4, byteorder='big')

        # create the packet header by combining the packetType, packetSequenceNumber, packetDataLength bytes together
        packetHeader = packetTypeBytes + packetSequenceNumberBytes + packetDataLengthBytes

        # create the packet by combining the packetHeader, packetBody together
        rudpPacket = packetHeader + packetData

        # send the RUDP packet to the receiver using the open socket
        log(f"sendRUDPPacket(): {rudpPacket} to: {self.receiverAddress}")
        self.rudpSocket.sendto(rudpPacket, self.receiverAddress)

        return rudpPacket
