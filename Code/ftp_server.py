#!/usr/bin/env python

import socket
import threading
import os
import sys
import time
import shutil
from tcpip_socket import TCPIPSocket
from rudp_socket import RUDPSocket
from ftp_exceptions import UserNotAuthenticatedException
from utils import fileProperty, generateUniqueThreadName, log, logCommand, getPortFromPool, returnPortToPool, getFTPPath


# server host ip that is used to bind when listening to incoming connection
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

# the default password of the default user
DEFAULT_PASSWORD = "1234"

# a flag to indicate if the users are allowed to delete files or folders on the server
allow_delete = True

# if this flag is True then FTP server uses TCPIP protocol, if this flag is False, then it uses RUDP
isTCPIP = True

# flag that indicates if the server is working, or shutting down
isListening = False

# dictionary that contains the active thread names
allThreads = {}

# this is the server socket that is used to accept incoming connections
mainServerSocket = None

# hold all the currently connected clients
allConnectedClients = {}


class FtpServerProtocol(threading.Thread):
    cwd = "/"
    threadName = "Th"
    dataSocketIP = "127.0.0.1"
    dataSocketPort = RETURN_PORT
    rest = False
    pasv_mode = False
    authenticated = False
    mode = 'A'
    startingPosition = 0
    isAppend = False
    # this is the port used by the server in passive mode to receive data from client
    passivePort = -1
    fileRenameFrom = None
    username = None
    passwd = None
    dataSocket = None
    passiveSocket = None

    # ----------------------------------- #
    # init the thread and set all members #
    # ----------------------------------- #
    def __init__(self, newCommandSocket, newThreadName):
        global allThreads

        # set the command socket for this client
        self.commandSocket = newCommandSocket

        # set the client ip address
        self.clientAddress = newCommandSocket.receiverAddress

        # set this thread name
        self.threadName = newThreadName

        # add this thread name to the allThreads dictionary, so the server will know this thread is working
        allThreads[self.threadName] = "Working"

        # init the thread super
        threading.Thread.__init__(self)


    def run(self):
        global isListening

        # when a client connects - send it a welcome message
        self.sendWelcome()

        while True:
            # if the server admin pressed q+Enter then close connection to the client and quit this thread
            # so the server can shut down properly
            if not isListening:
                self.QUIT('')
                break

            try:
                self.commandSocket.setTimeout(5.0)
                data = self.commandSocket.receive(1024).rstrip()
                if (data is not None) and (len(data) > 0):
                    # decode the received data as byte array and convert it (decode) into string using UTF8
                    try:
                        cmd = data.decode('utf-8')
                        log("Data from client: " + cmd)
                    except AttributeError:
                        cmd = data

                    try:
                        # parse command and arguments from the data that we received from the client
                        cmd, arg = cmd[0:4].strip().upper(), cmd[4:].strip() or ''

                        # try to find a function that has the same name as the received command
                        func = getattr(self, cmd)

                        # execute the function with the received arguments
                        func(arg)
                    except AttributeError as err:
                        self.sendCommand('500 Syntax error, command unrecognized.\r\n')
                        logCommand('Receive', err)
                    except Exception as err:
                        logCommand("Error, unknown command from client: ", err)
                        self.sendCommand('500 could not interpret your command, please try again.\r\n')
                    if not cmd:
                        break
            except socket.error as err:
                if err.__class__.__name__ != 'TimeoutError':
                    if 'forcibly closed' not in str(err):
                        logCommand('General Error while receiving data from client', err)
                    else:
                        break

        # once this thread run function has finished (got out of the while loop)
        # then log that the client has disconnected
        log("Client: " + str(self.clientAddress) + " disconnected")


    # ---------------------------------------------- #
    # this function returns the absolute path of the #
    # dir or file it received as dirPath argument    #
    # ---------------------------------------------- #
    def getAbsolutePath(self, dirPath):
        log('getAbsolutePath(' + dirPath + ')')
        # if user did not supply a path then use empty string (so we actually use CWD)
        if not dirPath:
            dirPath = ""

        # if user path starts with / then get the absolute path
        if dirPath.startswith(os.path.sep):
            result = os.path.abspath(dirPath)
        else:
            # if user path is relative (dos not starts with /)
            # then join the CWD and user path then get the absolute path
            result = os.path.abspath(os.path.join(self.cwd, dirPath))

        log('getAbsolutePath() returning: ' + result)
        return result

    # ------------------------------------------------------------------------------ #
    # this function opens a socket to the cient on the IP and port he has configured #
    # ------------------------------------------------------------------------------ #
    def openSocket(self):
        log('openSocket()')
        # check if user is authenticated
        self.isUserAuthenticated()

        if self.pasv_mode:
            # since client asked us to work in passive mode (FTP server launch a socket, and client connect to it)
            # instead of client launching a socket and sever connect to it
            log("openSocket(): waiting for client to connect in passive mode")
            self.dataSocket = self.passiveSocket.accept()
            log("openSocket(): connected to client in passive mode")
            self.dataSocketIP = self.dataSocket.receiverAddress[0]
            self.dataSocketPort = self.dataSocket.receiverAddress[1]
            log(f"openSocket(): dataSocketIP: {self.dataSocketIP} dataSocketPort: {self.dataSocketPort}")
        else:
            # create an outgoing connection socket
            if isTCPIP:
                self.dataSocket = TCPIPSocket()
            else:
                self.dataSocket = RUDPSocket()
            # connect to the client IP and port using the created socket
            dataSocketAddress = (self.dataSocketIP, self.dataSocketPort)
            self.dataSocket.connect(dataSocketAddress)
            log("openSocket(): connected to client in active mode")
            log(f"dataSocket IP: {self.dataSocketIP} Port: {self.dataSocketPort}")
            log(f"openSocket(): dataSocketIP: {self.dataSocketIP} dataSocketPort: {self.dataSocketPort}")


    # ---------------------------------------------- #
    # this function close a previously opened socket #
    # ---------------------------------------------- #
    def closeSocket(self):
        log('closeSocket()')
        try:
            # if there is an open data socket then close it
            if self.dataSocket is not None:
                self.dataSocket.close()

            # if there is an open server socket then close it
            if self.passiveSocket is not None:
                self.passiveSocket.close()
                returnPortToPool(self.passivePort)

        except socket.error as err:
            logCommand('closeSocket has failed', err)


    # ------------------------------------------------------------------------------- #
    # this function sends commands to the cient on the command socket (commandSocket) #
    # ------------------------------------------------------------------------------- #
    def sendCommand(self, cmd):
        # encode the cmd string into byte array
        sentLength = self.commandSocket.send(cmd.encode('utf-8'))
        return sentLength


    # ------------------------------------------------------------------ #
    # this function sends data to client on the data socket (dataSocket) #
    # the data sent to this function must be byte array                  #
    # ------------------------------------------------------------------ #
    def sendData(self, data):
        # send data on th socket as byte array
        self.dataSocket.send(data)


    # ------------------------------------------- #
    #  this function handles the OPTS ftp command #
    # ------------------------------------------- #
    def OPTS(self, onOff):
        log("OPTS(" + onOff + ")")
        self.sendCommand('202 UTF8 mode is always enabled. No need to send this command\r\n')


    # ------------------------------------------- #
    #  this function handles the AUTH ftp command #
    # ------------------------------------------- #
    def AUTH(self, user):
        log("AUTH(" + user + ")")
        self.sendCommand('500 Insecure server, it does not support FTP over TLS/SSL.\r\n')


    # ------------------------------------------- #
    #  this function handles the USER ftp command #
    # ------------------------------------------- #
    def USER(self, user):
        log("USER(" + user + ")")

        # if no user has been supplied - return error to the client
        if not user:
            self.sendCommand('501 Missing required argument.\r\n')
        else:
            # if the correct user has been supplied then set it to the username member
            if user == DEFAULT_USER:
                self.username = user
            else:
                # if the wrong user has been supplied then reset the username member
                self.username = None

        # for security reasons always ask for a password (so a hacker cannot know the real usernames of this server)
        self.sendCommand('331 Please, specify the password.\r\n')


    # ------------------------------------------- #
    #  this function handles the PASS ftp command #
    # ------------------------------------------- #
    def PASS(self, passwd):
        log("PASS(" + passwd + ")")

        # if a password is empty or not the correct password, or the username is wrong then return error to the client
        if (not passwd) or (self.username != DEFAULT_USER) or (passwd != DEFAULT_PASSWORD):
            # reset user and password so next attempts will start from scratch
            self.username = None
            self.passwd = None
            self.sendCommand('530 Login incorrect.\r\n')
        else:
            # if the user is the correct user, and the password is
            # the correct password then mark client as authenticated
            self.passwd = passwd
            self.sendCommand('230 Login successful.\r\n')
            self.authenticated = True


    # -------------------------------------------------------------------------- #
    # this function checks if the user is authenticated, if not returns an error #
    # -------------------------------------------------------------------------- #
    def isUserAuthenticated(self):
        # check if user is loggedon (authenticated), if not return error and ask to login
        if not self.authenticated:
            self.sendCommand('530 Please log in with USER and PASS first.\r\n')
            log("User not authenticated, please login first")
            raise UserNotAuthenticatedException('User not loggedin')


    # ------------------------------------------------------------------------- #
    # this function handles the EPRT command which is an alias for PORT command #
    # ------------------------------------------------------------------------- #
    def EPRT(self, args):
        self.PORT(args)


    # ---------------------------------------------------------------------- #
    # handle port command by setting the received client IP address and port #
    # ---------------------------------------------------------------------- #
    def PORT(self, args):
        log("PORT(" + args + ")")

        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            if self.pasv_mode:
                self.passiveSocket.close()
                self.pasv_mode = False

            # convert arguments into array (split by ,)
            ipAndPortArray = args.split(',')

            # get the first 4 parts of the array and join them with . into an ip adress
            self.dataSocketIP = '.'.join(ipAndPortArray[:4])

            # get the last 2 array entries and calculate the client port
            # (bit shift left the first part, and add to it the second part)
            self.dataSocketPort = (int(ipAndPortArray[4]) << 8) + int(ipAndPortArray[5])

            # return message to the client that the port configuration has succeeded
            self.sendCommand('200 PORT command successful.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("Port function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # ------------------------------------------------------------------------- #
    # this function handles the NLST command which is an alias for LIST command #
    # ------------------------------------------------------------------------- #
    def NLST(self, dirpath):
        self.LIST(dirpath)


    # ---------------------------------------------------------------------- #
    # handle LIST command by opening a dataSocket to the client at the port  #
    # and address previously configured, and sending the folder data to that #
    # socket, at the end close that socket                                   #
    # ---------------------------------------------------------------------- #
    def LIST(self, dirpath):
        log("LIST(" + dirpath + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # get the absolute path to the file / folder
            pathname = self.getAbsolutePath(dirpath)

            if not os.path.exists(pathname):
                # file or folder does not exist - return error to the client
                self.sendCommand("550 Couldn't open the file or directory.\r\n")
            else:
                # send to client that we have received the request and starting to work on it
                self.sendCommand('150 Starting data transfer.\r\n')

                # open socket connection to client on the address and port he has set using the previous PORT command
                self.openSocket()

                # if the user asked to list a file (not a directory) then get
                # file properties and return them on the previously opened socket
                if not os.path.isdir(pathname):
                    # get file properties (change date / size / owner...)
                    fileMessage = fileProperty(pathname)
                    # send data to client on data socket as byte array
                    # (inside the function it will decide if to send text or binary byte array)
                    fileMessageByteArray = bytes(fileMessage + '\r\n', encoding="utf-8")
                    self.sendData(fileMessageByteArray)

                else:
                    # if this is a directory (not a file) then loop through the directory
                    # files and folders and write their properties to the previously opened socket
                    for file in os.listdir(pathname):
                        # get file/folder properties (change date / size / owner...)
                        fileMessage = fileProperty(os.path.join(pathname, file))
                        # send data to client on data socket as byte array
                        # (inside the function it will decide if to send text or binary byte array)
                        fileMessageByteArray = bytes(fileMessage + '\r\n', encoding="utf-8")
                        self.sendData(fileMessageByteArray)

                # at the end close the previously opened socket
                self.closeSocket()

                # send success message to the client
                self.sendCommand('226 Operation successful.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("LIST function failed", err)
                self.closeSocket()
                self.sendCommand('500 Operation Failed.\r\n')


    # -------------------------- #
    # alias for the CWD function #
    # -------------------------- #
    def XCWD(self, cmd):
        self.CWD(cmd)


    # --------------------------------------------------------------------- #
    # change the current working directory to the received dirpath argument #
    # --------------------------------------------------------------------- #
    def CWD(self, dirpath):
        log("CWD(" + dirpath + ")")

        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # get the absolute path to the file / folder
            pathname = self.getAbsolutePath(dirpath)

            # convert the absolute path into ftp server absolute path
            pathname = getFTPPath(pathname)

            # if dirpath is not a directory or dirpath does not exist then return an error
            if not os.path.exists(pathname) or not os.path.isdir(pathname):
                self.sendCommand('550 CWD failed Directory not exists.\r\n')
            else:
                # set CWD member to the received dirpath and return success message
                self.cwd = pathname
                self.sendCommand('250 CWD Command successful.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("CWD function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # -------------------------- #
    # alias for the PWD function #
    # -------------------------- #
    def XPWD(self, cmd):
        self.PWD(cmd)


    # ----------------------------------------------------------------- #
    # this function returns the current working directory to the client #
    # ----------------------------------------------------------------- #
    def PWD(self, cmd):
        log("PWD(" + cmd + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            self.sendCommand('257 "%s".\r\n' % self.cwd)
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("PWD function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # ------------------------------------------------------ #
    # this function sets the transfer type (Ascii or Binary) #
    # ------------------------------------------------------ #
    def TYPE(self, type):
        log("TYPE(" + type + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # if client sent i or I then set transfer mode to binary
            if type.upper() == 'I':
                self.mode = 'I'
                self.sendCommand('200 Binary mode.\r\n')


            # if client sent a or A then set transfer mode to Ascii
            elif type.upper() == 'A':
                self.mode = 'A'
                self.sendCommand('200 Ascii mode.\r\n')


            # if client sent type other then I or A then return an error response
            else:
                self.sendCommand(type + ': unknown mode.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("TYPE function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # ------------------------------------------------------------- #
    # this function enters the server into a passive receiving mode #
    # the server create s a socket, starts to listen and send the   #
    # socket data to the client s he can send datat to the server   #
    # on that socket                                                #
    # ------------------------------------------------------------- #
    def PASV(self, cmd):
        log("PASV(" + cmd + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # mark passive mode flag to true
            self.pasv_mode = True

            # create a new server socket based on the selected protocol
            if isTCPIP:
                self.passiveSocket = TCPIPSocket()
            else:
                self.passiveSocket = RUDPSocket()

            # bind server socket to the server IP and unique port number (so each client can have a unique port number)
            self.passivePort = getPortFromPool()
            self.passiveSocket.listen((SERVER_HOST, self.passivePort))

            # send the client that we entered a passive mode, with the socket info
            self.sendCommand('227 Entering Passive Mode (%s,%u,%u).\r\n' %
                             (','.join(SERVER_HOST.split('.')), self.passivePort >> 8 & 0xFF, self.passivePort & 0xFF))
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("PASV function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # ------------------------------------------------- #
    # this function returns to the client the server    #
    # operating system type (Windows / Linux / OSX ...) #
    # ------------------------------------------------- #
    def SYST(self, arg):
        logCommand('SYS', arg)
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            self.sendCommand('215 %s type.\r\n' % sys.platform)
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("SYST function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # --------------------------- #
    # alias for the CDUP function #
    # --------------------------- #
    def XCUP(self, cmd):
        self.CDUP(cmd)


    # ------------------------------------------------ #
    # this function sets the current working directory #
    # to it's parent directory                         #
    # ------------------------------------------------ #
    def CDUP(self, cmd):
        log('CDUP()')
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # set the CWD to its parent folder (add .. to the path)
            self.cwd = os.path.abspath(os.path.join(self.cwd, '..'))
            # return success message to the client
            self.sendCommand('250 CDUP command successful.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("CDUP function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # --------------------------------------------------------------- #
    # this function deletes file or folder from the server hard drive #
    # --------------------------------------------------------------- #
    def DELE(self, filename):
        log("DELE(" + filename + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # get the absolute path to the file / folder
            pathname = self.getAbsolutePath(filename)

            # if the file or folder does not exist the return error message to the client
            if not os.path.exists(pathname):
                self.sendCommand('550 Failed to delete file: %s, file does not exists.\r\n' % pathname)

            # if user is not allowed to delete files and folders from the server then return an error
            elif not allow_delete:
                self.sendCommand('450 Failed to delete file: %s, server does not allow delete.\r\n' % pathname)

            # if the user is allowed to delete files and foldersm and the file/folder exist - then delete it
            else:
                os.remove(pathname)
                self.sendCommand('250 File deleted.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("DELE function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # -------------------------- #
    # alias for the MKD function #
    # -------------------------- #
    def XMKD(self, dirname):
        self.MKD(dirname)


    # ----------------------------------------------- #
    # this function creates a directory on the server #
    # ----------------------------------------------- #
    def MKD(self, dirname):
        log("MKD(" + dirname + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # get the absolute path to the file / folder
            pathname = self.getAbsolutePath(dirname)

            # if the directory that we try to create already exist then return error message
            if os.path.exists(pathname):
                self.sendCommand('550 MKD failed, directory "%s" already exists.\r\n' % pathname)
            else:
                # create the directory at the current working directory
                os.mkdir(pathname)
                self.sendCommand('257 Directory created.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("MKD function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # -------------------------- #
    # alias for the XRMD function #
    # -------------------------- #
    def XRMD(self, dirname):
        self.RMD(dirname)


    # ------------------------------------------------ #
    # this function deletes a directory on the server  #
    # it uses shutil to delete the folder & everything #
    # underneath it (remove tree)                      #
    # ------------------------------------------------ #
    def RMD(self, dirname):
        log("RMD(" + dirname + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # get the absolute path to the file / folder
            pathname = self.getAbsolutePath(dirname)

            # if the directory that we try to delete doesn't exist then return error message
            if not os.path.exists(pathname):
                self.sendCommand('550 RMD failed, directory "%s" does not exists.\r\n' % pathname)

            # if user is not allowed to delete files and folders from the server then return an error
            elif not allow_delete:
                self.sendCommand('450 Failed to delete folder: %s, server does not allow delete.\r\n' % pathname)

            # remove the directory that we received
            else:
                shutil.rmtree(pathname)
                self.sendCommand('250 Directory deleted.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("RMD function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # ------------------------------------------------ #
    # this function receives a file/dir name with path #
    # if the file/dir name is not empty and the file   #
    # /dir exist then save it into fileRenameFrom      #
    # ------------------------------------------------ #
    def RNFR(self, filename):
        log("RNFR(" + filename + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # get the absolute path to the file / folder
            pathname = self.getAbsolutePath(filename)

            # if the file/dir that we try to rename doesn't exist then return error message
            if not os.path.exists(pathname):
                self.sendCommand('550 RNFR failed, file/dir "%s" does not exists.\r\n' % pathname)
            else:
                self.fileRenameFrom = pathname
                self.sendCommand("350 File exists, ready for destination name.\r\n")
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("RNFR function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # ------------------------------------------------ #
    # this function receives a file/dir name with path #
    # if the file/dir name is not empty and the file   #
    # /dir exist then rename from: fileRenameFrom      #
    # to the received file/dir name                    #
    # ------------------------------------------------ #
    def RNTO(self, filename):
        log("RNTO(" + filename + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # get the absolute path to the file / folder
            fileRenameTo = self.getAbsolutePath(filename)

            # if the file/dir that we try to rename exist then return error message
            if os.path.exists(fileRenameTo):
                self.sendCommand('550 RNTO failed, file/dir "%s" already exists.\r\n' % fileRenameTo)
            else:
                # perform the rename action
                os.rename(self.fileRenameFrom, fileRenameTo)
                # return success message
                self.sendCommand('250 File or directory renamed successfully.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("RNTO function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # ------------------------------------ #
    # this function set the read starting  #
    # position of the file we are about to #
    # download, it will tell the server at #
    # what point to start reading the file #
    # and send the data from that position #
    # ------------------------------------ #
    def REST(self, newStartingPosition):
        log("REST(" + newStartingPosition + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # convert the received newStartingPosition from string to int and save it
            self.startingPosition = int(newStartingPosition)
            self.sendCommand('250 File position reseted.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("REST function failed", err)
                self.sendCommand('500 Operation Failed.\r\n')


    # ---------------------------------------- #
    # this function retrieves a file in binary #
    # or ascii mode, and it will retrieve it   #
    # from the startingPosition that is 0 by   #
    # default or the client can set it by      #
    # calling the REST function                #
    # ---------------------------------------- #
    def RETR(self, filename):
        log("RETR(" + filename + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # if user did not supply a filename then return error message
            if not filename:
                self.sendCommand('500 Operation Failed, Please supply a filename to download.\r\n')
            else:
                # get the absolute path to the file / folder
                fileToDownload = self.getAbsolutePath(filename)

                # check if the file to download exist on the server
                if not os.path.exists(fileToDownload):
                    self.sendCommand('500 Operation Failed, The filename does not exist.\r\n')

                else:
                    # if we are working in binary mode then open the file to Read in binary mode
                    if self.mode == 'I':
                        file = open(fileToDownload, 'rb')
                    else:
                        # if we are working in ascii mode then open the file to Read in ascii mode
                        file = open(fileToDownload, 'r')

                    # send message to client to tell it that we are working on his request
                    self.sendCommand('150 Opening data connection.\r\n')

                    # open the dataSocket to the client
                    self.openSocket()
                    # set read starting position to the startingPosition var
                    file.seek(self.startingPosition)

                    # reset the starting position back to 0 so next download will start from the beginning of the file
                    self.startingPosition = 0

                    # loop and read all the data from the file and write it into the socket
                    # until there is nothing more to read
                    while True:
                        if self.mode == 'I':
                            # read 1024 bytes from the file
                            data = file.read(1024)

                            # check if data was read from the file, if not - get out of the loop (finish reading)
                            if not data:
                                break
                        else:
                            # because the client asked us to work in ascii mode, we need to send it a CRLF character
                            # at the end of each line, so make sure each line ends with CRLF (\r\n)
                            currentLine = file.readline()

                            # check if data was read from the file, if not - get out of the loop (finish reading)
                            if not currentLine:
                                break

                            if not currentLine.endswith("\r\n"):
                                # remove the last character [should be \n (Unix systems) or \r (Mac systems)]
                                currentLine = currentLine[:-1]
                                # add to the end of the line the CRLF end line characters (Windows systems)
                                data = bytes(currentLine + '\r\n', 'utf-8')

                        # send to the dataSocket the 1024 bytes you read from file, the sendData function will decide
                        # if to send it binary or ascii (text) base on the client preferences
                        self.sendData(data)

                    # close the file and allow others to use it
                    file.close()

                    # close the dataSocket
                    self.closeSocket()

                    # send the client a success message
                    self.sendCommand('226 Transfer completed.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("RETR function failed", err)
                self.closeSocket()
                self.sendCommand('500 Operation Failed.\r\n')


    # --------------------------------------------------- #
    # this function receives a file/dir name with path    #
    # if the file/dir name is empty then return error     #
    # based on the mode open the file for binary-write    #
    # or string-write, then open the socket to the client #
    # and start reading bytes from that socket in 1024    #
    # chunks, and write them into the file, unil there    #
    # is nothing left to read, then close the file and    #
    # close the socket & send success message to client   #
    # --------------------------------------------------- #
    def STOR(self, filename):
        log("STOR(" + filename + ")")
        try:
            # check if user is authenticated
            self.isUserAuthenticated()

            # if user did not supply a filename then return error message
            if not filename:
                self.sendCommand('500 Operation Failed, Please supply a filename to upload.\r\n')
            else:
                # get the absolute path to the file / folder
                fileToUpload = self.getAbsolutePath(filename)

                if self.isAppend:
                    # open the file to Write from the end of the file (append) in binary mode
                    file = open(fileToUpload, 'ab')
                    # reset the append flag back to it's default value (false)
                    self.isAppend = False
                else:
                    # open the file to Write (new file or overwrite) in binary mode (always write byte array to a file)
                    file = open(fileToUpload, 'wb')

                # send message to client to tell it that we are working on his request
                self.sendCommand('150 Opening data connection.\r\n')

                # open the dataSocket to the client
                self.openSocket()

                # loop and read all the data from the socket and write it into the file
                # until there is nothing more to read
                while True:
                    # read from the socket 1024 bytes/chars (based on client preferences)
                    data = self.dataSocket.receive(1024)

                    # check if data was received, if not - get out of the loop (finish reading)
                    if not data:
                        break

                    # # if client asked us to receive in ascii mode, then we need to convert (decode) the strings into
                    # # byte array using UTF8 mapping
                    # if self.mode == 'A':
                    #     data = data.decode("utf-8")

                    # write the 1024 bytes you read from the socket into the file
                    file.write(data)

                # close the file and allow others to use it
                file.close()

                # close the dataSocket
                self.closeSocket()

                # send the client a success message
                self.sendCommand('226 Transfer completed.\r\n')
        except Exception as err:
            if err.__class__.__name__ != 'UserNotAuthenticatedException':
                logCommand("STOR function failed", err)
                self.closeSocket()
                self.sendCommand('500 Operation Failed.\r\n')


    def APPE(self, filename):
        log("APPE(" + filename + ")")
        self.isAppend = True
        self.STOR(filename)


    # ------------------------------------------- #
    #  this function handles the HELP ftp command #
    # ------------------------------------------- #
    def HELP(self, arg):
        logCommand('HELP', arg)
        help = """
            214
            USER [name], Its argument is used to specify the user's string. It is used for user authentication.
            PASS [password], Its argument is used to specify the user password string.
            PASV The directive requires server-DTP in a data port.
            PORT [h1, h2, h3, h4, p1, p2] The command parameter is used for the data connection data port
            LIST [dirpath or filename] This command allows the server to send the list to the passive DTP. If
                 the pathname specifies a path or The other set of files, the server sends a list of files in
                 the specified directory. Current information if you specify a file path name, the server will
                 send the file.
            CWD Type a directory path to change working directory.
            PWD Get current working directory.
            CDUP Changes the working directory on the remote host to the parent of the current directory.
            DELE Deletes the specified remote file.
            MKD Creates the directory specified in the RemoteDirectory parameter on the remote host.
            RNFR [old name] This directive specifies the old pathname of the file to be renamed. This command
                 must be followed by a "heavy Named "command to specify the new file pathname.
            RNTO [new name] This directive indicates the above "Rename" command mentioned in the new path name
                 of the file. These two Directive together to complete renaming files.
            REST [position] Marks the beginning (REST) ​​The argument on behalf of the server you want to re-start
                 the file transfer. This command and Do not send files, but skip the file specified data checkpoint.
            RETR This command allows server-FTP send a copy of a file with the specified path name to the data
                 connection The other end.
            STOR This command allows server-DTP to receive data transmitted via a data connection, and data is
                 stored as A file server site.
            APPE This command allows server-DTP to receive data transmitted via a data connection, and data is stored
                 as A file server site.
            SYS  This command is used to find the server's operating system type.
            HELP Displays help information.
            QUIT This command terminates a user, if not being executed file transfer, the server will shut down
                 Control connection.
            """
        self.sendCommand(help + "\r\n")


    # ------------------------------------------- #
    #  this function handles the QUIT ftp command #
    #  send goodbye to client, close the client   #
    #  socket, remove thread name from allThreads #
    # ------------------------------------------- #
    def QUIT(self, cmd):
        global allThreads
        log('QUIT')
        try:
            self.sendCommand('221 Goodbye.\r\n')
            self.closeSocket()
        except Exception as err:
            log("Warning: failed to close sockets for thread: " + self.threadName + " due to error: " + err)
        finally:
            allThreads.pop(self.threadName)


    # ------------------------------------------- #
    #  this function handles the open ftp command #
    #  when a client opens a socket to the server #
    #  the server responds with a WELCOME message #
    # ------------------------------------------- #
    def sendWelcome(self):
        self.sendCommand('220 Welcome.\r\n')


# ----------------------------------------------------- #
#  this function starts the server main socket and wait #
#  for clients to connect, once a client connects, it   #
#  creates a new FtpServerProtocol thread, and start it #
#  so it can handle the client requests                 #
# ----------------------------------------------------- #
def serverListener():
    global mainServerSocket
    global isListening

    try:
        # create the server socket based on the selected protocol
        if isTCPIP:
            mainServerSocket = TCPIPSocket()
        else:
            mainServerSocket = RUDPSocket()

            # start the server main socket that listens to client incoming connections
        mainServerAddress = (SERVER_HOST, SERVER_PORT)
        mainServerSocket.listen(mainServerAddress)

        # mark the server as listening
        isListening = True
        logCommand('Server started', f'Listen on: {SERVER_HOST}, {SERVER_PORT}')
    except Exception as err:
        logCommand("Error: cannot launch server, error", err)

    # wait for clients to connect
    while True:
        try:
            # wait for incoming connections and accept socket connections from clients
            clientSocket = mainServerSocket.accept()
            newClientID = f"{clientSocket.receiverAddress[0]}:{clientSocket.receiverAddress[1]}"

            if newClientID not in allConnectedClients:
                allConnectedClients[newClientID] = "Connected"

                # create new thread that will handle the incoming socket
                clientThread = FtpServerProtocol(clientSocket, generateUniqueThreadName())

                # start the thread so it will handle the client requests
                clientThread.start()
                logCommand('Accept', 'New client connected %s, %s' % clientSocket.receiverAddress)

        except Exception as err:
            if isListening:
                logCommand("Error: cannot accept connection, error: ", err)
            else:
                log("Warning: cannot accept any more connections, server is shutting down")
                break


if __name__ == "__main__":
    try:
        # start the ftp server in a separated thread so the main thread can listen to Q and Ctrl+C keys
        logCommand('Start ftp server', 'press q and Enter or Ctrl+C to stop the ftp server')
        listener = threading.Thread(target=serverListener)
        listener.start()

        # if server admin asked to stop the FTP server - quit
        if input().lower() == "q":
            isListening = False
            while True:
                log("Waiting for all clients to disconnect ...")
                time.sleep(2)
                if len(allThreads) == 0:
                    break
            time.sleep(0.5)
            mainServerSocket.close()
            sys.exit()
    except KeyboardInterrupt:
        print("Ctrl+C pressed, Shutting down FTP Server")
        os._exit(-1)



'''
 Accept
========
the main socket exists if the server and client works using TCPIP protocol the the server
listen on the mainServerSocket for incoming connections, and once a client connects,
the incoming socket (commandSocket) is used to accept commands from the client

    --------              --------
   |        |    main    |        |
   | Client |   Socket   | Server |
   |        |  ------->  |        |
    --------              --------



 Commands
==========
- USER
- PASS
- PORT
- LIST ...
  client sends commands to server on the commandSocket, and server return responses
  for that command to the client on the commandSocket
  
    --------              --------
   |        |  command   |        |
   | Client |   Socket   | Server |
   |        |  ------->  |        |
    --------              --------



  Active Mode
==============
- LIST response (dir/files properties)
- GET response (download file)
- PUT response (upload file)
  for this commands the client needs another socket (dataSocket) so it will receive
  the extra data on that socket, 
  in ACTIVE mode the client creates the socket and listens to incoming connections,
  and tells the server that it has opened that socket, the server returns data to the client on that socket
  
    --------              --------
   |        |    data    |        |
   | Client |   Socket   | Server |
   |        |  <-------  |        |
    --------              --------




 Passive Mode
==============
- LIST response (dir/files properties)
- GET response (download file)
- PUT response (upload file)
  for this commands the client needs another socket (dataSocket) so it will receive
  the extra data on that socket, 
  in PASSIVE mode the server creates a socket and listens to incoming connections,
  and tells the client that it has opened that socket, the client connects, and the returning socket from
  the accept command is then used as a dataSocket, the server returns data to the client on the dataSocket
  
    --------                  --------
   |        | ---passive-->  |        |
   | Client |                | Server |
   |        | <---data-----  |        |
    --------                  --------

'''