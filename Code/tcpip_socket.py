import socket

# maximum seconds the socket can be idle before an exception is raised
SOCKET_MAX_TIMEOUT = 60

# limit to the maximum simultaneous connections this socket can accept
MAX_SIMULTANEOUS_CONNECTIONS = 5


class TCPIPSocket:
    # the ipv4 address and port of the receiver side (or this server as a receiver)
    receiverAddress = None

    # the tcpip socket we open to the receiver side as senders, or as a receiver for listening
    tcpipSocket = None


    # ----------------------------------------------------- #
    # connects to a receiver using the receiver host & port #
    # ----------------------------------------------------- #
    def connect(self, address):
        # save the receiver address
        self.receiverAddress = address
        # open a TCPIP socket and connect to the receiver host and port
        self.tcpipSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.setTimeout(SOCKET_MAX_TIMEOUT)
        # connect to the client IP and port using the created socket
        self.tcpipSocket.connect(address)


    # ----------------- #
    # closes the socket #
    # ----------------- #
    def close(self):
        # close the tcpip socket
        self.tcpipSocket.close()


    # -------------------------------- #
    # sends bytes data to the receiver #
    # -------------------------------- #
    def send(self, dataToSend):
        self.tcpipSocket.send(dataToSend)


    # ------------------------------------------------------------ #
    # sets the socket max timeout for connect/send/receive actions #
    # ------------------------------------------------------------ #
    def setTimeout(self, socketMaxTimeout):
        self.tcpipSocket.settimeout(socketMaxTimeout)


    # --------------------------------------- #
    # receives bytes data from sender clients #
    # --------------------------------------- #
    def receive(self, maxBufferLength):
        dataReceived = self.tcpipSocket.recv(maxBufferLength)
        return dataReceived


    # --------------------------------------------------------------------------- #
    # binds this socket to ip & port and stars to listen for incoming connections #
    # --------------------------------------------------------------------------- #
    def listen(self, address):
        # save the receiver address
        self.receiverAddress = address
        # open a TCPIP socket and bind it to the host & port
        self.tcpipSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcpipSocket.bind(address)
        self.tcpipSocket.listen(MAX_SIMULTANEOUS_CONNECTIONS)


    # --------------------------------------------------------------------- #
    # wait for incoming connections, once a connection is accepted, it will #
    # return the connected client socket and client address (ip & port)     #
    # --------------------------------------------------------------------- #
    def accept(self):
        # wait & accept incoming connections
        clientSocket, clientAddress = self.tcpipSocket.accept()
        # create a new TCPIPSocket for the connected client and return it to caller
        clientTCPIPSocket = TCPIPSocket()
        # set client parameters to the TCPIPSocket
        clientTCPIPSocket.tcpipSocket = clientSocket
        clientTCPIPSocket.receiverAddress = clientAddress
        # return the new TCPIPSocket and clientAddress
        return clientTCPIPSocket
