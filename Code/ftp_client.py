#!/usr/bin/env python

import socket
import threading
import os
import time
from tcpip_socket import TCPIPSocket
from rudp_socket import RUDPSocket

try:
    SERVER_HOST = socket.gethostbyname(socket.gethostname())
except socket.gaierror:
    SERVER_HOST = '127.0.0.1'

# this is the port the server use when listening to incoming connections
SERVER_PORT = 20383

# the default port number for client dataSocket connection
RETURN_PORT = 30084  # return to client port

# the default user that can connect to the server
DEFAULT_USER = "user"

# maximum transmission unit, the max size of a packet
MTU = 5000

ftpServerIP = SERVER_HOST

clientSocket = None

isTCPIP = True


def sendCommandToServer(commandWithArguments):
    global clientSocket
    try:
        clientSocket.send(bytes(commandWithArguments, "utf-8"))
        # allow server time to respond
        time.sleep(0.2)
        serverAnswer = clientSocket.receive(MTU)
        if serverAnswer:
            print(serverAnswer.decode("utf-8"))
        else:
            print(f"Server did not respond to command: {commandWithArguments}")
    except Exception as err:
        print(f"Server command failed: {str(err)}")


def receiveFromServer():
    global ftpServerIP, RETURN_PORT

    if isTCPIP:
        listenerSocket = TCPIPSocket()
    else:
        listenerSocket = RUDPSocket()
    listenerSocket.listen((ftpServerIP, RETURN_PORT))
    newSocket = listenerSocket.accept()

    try:
        while True:
            newSocket.setTimeout(5)
            receivedBytes = newSocket.receive(MTU)
            if receivedBytes:
                receivedMessage = str(receivedBytes, "utf-8")
                print(f"{receivedMessage}")
    except Exception as globalError:
        pass
    finally:
        try:
            newSocket.close()
        except Exception as closeErr:
            pass
        try:
            listenerSocket.close()
        except Exception as closeErr:
            pass


if __name__ == "__main__":
    while True:
        serverReply = ''
        try:
            inputFromClient = input("ftp: ")
            if inputFromClient.lower() == "quit":
                os._exit(-1)
            if inputFromClient.lower() == "open":
                ftpServerIP = input(f"Server IP [{SERVER_HOST}]: ") or SERVER_HOST
                ftpServerPort = int(input(f"Port [{SERVER_PORT}]: ") or SERVER_PORT)
                # open a TCPIP or RUDP socket and connect to the receiver host and port
                if isTCPIP:
                    clientSocket = TCPIPSocket()
                else:
                    clientSocket = RUDPSocket()
                clientSocket.connect((ftpServerIP, ftpServerPort))
                welcomeMessage = clientSocket.receive(MTU)
                if welcomeMessage:
                    print(welcomeMessage.decode("utf-8"))
                print(f"Connected to {ftpServerIP}:{ftpServerPort}")
                sendCommandToServer("OPTS")
                ftpServerUser = input(f"User [{DEFAULT_USER}]: ") or DEFAULT_USER
                sendCommandToServer(f"USER {ftpServerUser}")
                ftpServerPassword = input(f"Password: ")
                sendCommandToServer(f"PASS {ftpServerPassword}")
            elif inputFromClient.lower() == "dir" or inputFromClient.lower() == "list":
                tempIP = ','.join(ftpServerIP.split('.'))
                RETURN_PORT = RETURN_PORT + 1
                tempPort = RETURN_PORT >> 8 & 0xFF
                tempPort2 = RETURN_PORT & 0xFF
                sendCommandToServer(f"PORT {tempIP},{tempPort},{tempPort2}")
                listener = threading.Thread(target=receiveFromServer)
                listener.start()
                sendCommandToServer(f"LIST")
            elif inputFromClient.lower().startswith("cd"):
                sendCommandToServer(f"CWD {inputFromClient[2:]}")
            elif inputFromClient.lower() == "help":
                print("ftp_client [command] [arguments]")
                print("commands:")
                print("  OPEN")
                print("     opens a connection to the ftp server, the command will ask you for server ip and port")
                print("  DIR or LIST")
                print("     lists the files and folders in the Current Working Directory (CWD)")
                print("  PWD")
                print("     returns the Current Working Directory (CWD)")
                print("  CD or CWD")
                print("     returns the Current Working Directory (CWD)")
                print("  QUIT")
                print("     exit this client and close connection to the server")
                print("  HELP")
                print("     show this help screen")
            else:
                if len(inputFromClient) > 0:
                    sendCommandToServer(inputFromClient)

        except Exception as err:
            print(f"Error occurred in client: {str(err)}")
        except KeyboardInterrupt:
            print("Ctrl+C pressed, Shutting down FTP Server")
            os._exit(-1)
