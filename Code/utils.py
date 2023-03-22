#!/usr/bin/env python

from pathlib import Path
import time
import os
import stat
import random
import threading


portNumberLock = threading.Lock()
portsDictionary = {30080: 'free', 30081: 'free', 30082: 'free', 30083: 'free', 30084: 'free'}


def log(logMessage):
    print("%s" % (time.strftime("%Y-%m-%d %H-%M-%S [-] " + str(logMessage))))


def logCommand(func, cmd):
    logmsg: str = time.strftime("%Y-%m-%d %H-%M-%S [-] " + func)
    print("\033[31m%s\033[0m: \033[32m%s\033[0m" % (logmsg, str(cmd)))


# ----------------------------------------------------- #
# this function receives an absolute path and then      #
# convert it into ftp path (absolute server linux path) #
# for example: c:\temp\111\my.txt                       #
# will convert to: /temp/111/my.txt                     #
# ----------------------------------------------------- #
def getFTPPath(absolutPath):
    # remove the c:\ or other drive from the absolutPath
    relativeToRootPath = os.path.relpath(absolutPath, "/")
    # replace all backslash into forward slash (windows slash to linux slash)
    relativeToRootPath = relativeToRootPath.replace('\\', '/')
    # add the root slash so it will make the final path as absolute ftp server path
    relativeToRootPath = "/" + relativeToRootPath
    return relativeToRootPath


def getCurrentMilliseconds():
    return round(time.time() * 1000)


def generateUniqueThreadName():
    randomThreadNumber = random.randint(0, 9999)
    currentMilli = getCurrentMilliseconds()
    uniqueThreadName = "Th-" + str(currentMilli) + str(randomThreadNumber)
    return uniqueThreadName


def getPortFromPool():
    with portNumberLock:
        for currentPort in portsDictionary:
            if portsDictionary[currentPort] == "free":
                portsDictionary[currentPort] = "occupied"
                return currentPort


def returnPortToPool(portNumber):
    with portNumberLock:
        portsDictionary[portNumber] = "free"


# this function returns the file mode as a string example: drwxr--r--
def getFileMode(filepath):
    fileStat = os.stat(filepath)

    # init the fileModeString with empty string
    fileModeString: str = ''

    # get the file/folder stat mode
    fileMode = fileStat.st_mode

    # if this file/folder is a dir then change fileModeString to start with d (for directory)
    if (fileMode & stat.S_IFDIR) > 0:
        fileModeString = 'd'
    else:
        fileModeString = '-'

    # if USER has a read permission for this file/folder then add R to fileModeString
    if (fileMode & stat.S_IRUSR) > 0:
        fileModeString = fileModeString + 'r'
    else:
        fileModeString = fileModeString + '-'

    # if USER has write permission for this file/folder then add WW to fileModeString
    if (fileMode & stat.S_IWUSR) > 0:
        fileModeString = fileModeString + 'w'
    else:
        fileModeString = fileModeString + '-'

    # if USER has execute permission for this file/folder then add X to fileModeString
    if (fileMode & stat.S_IXUSR) > 0:
        fileModeString = fileModeString + 'x'
    else:
        fileModeString = fileModeString + '-'

    # if GROUP has a read permission for this file/folder then add R to fileModeString
    if (fileMode & stat.S_IRGRP) > 0:
        fileModeString = fileModeString + 'r'
    else:
        fileModeString = fileModeString + '-'

    # if GROUP has write permission for this file/folder then add WW to fileModeString
    if (fileMode & stat.S_IWGRP) > 0:
        fileModeString = fileModeString + 'w'
    else:
        fileModeString = fileModeString + '-'

    # if GROUP has execute permission for this file/folder then add X to fileModeString
    if (fileMode & stat.S_IXGRP) > 0:
        fileModeString = fileModeString + 'x'
    else:
        fileModeString = fileModeString + '-'

    # if OTHERS has a read permission for this file/folder then add R to fileModeString
    if (fileMode & stat.S_IROTH) > 0:
        fileModeString = fileModeString + 'r'
    else:
        fileModeString = fileModeString + '-'

    # if OTHERS has write permission for this file/folder then add WW to fileModeString
    if (fileMode & stat.S_IWOTH) > 0:
        fileModeString = fileModeString + 'w'
    else:
        fileModeString = fileModeString + '-'

    # if OTHERS has execute permission for this file/folder then add X to fileModeString
    if (fileMode & stat.S_IXOTH) > 0:
        fileModeString = fileModeString + 'x'
    else:
        fileModeString = fileModeString + '-'

    return fileModeString


# this function returns the number of hard links to the file/folder,
# a hard link is a directory has a link to that file
def getFilesNumber(filepath):
    fileStat = os.stat(filepath)
    return str(fileStat.st_nlink)


# this function returns the file/folder owner user id
def getUser(filepath):
    fileStat = os.stat(filepath)
    return str(fileStat.st_uid)  # pathToFile.owner()


# this function returns the file/folder owner group id
def getGroup(filepath):
    fileStat = os.stat(filepath)
    return str(fileStat.st_gid)  # pathToFile.group()


# this function returns the file size
def getSize(filepath):
    fileStat = os.stat(filepath)
    return str(fileStat.st_size)


# this function returns the last time this file/folder changed
def getLastTime(filepath):
    fileStat = os.stat(filepath)
    return time.strftime('%b %d %H:%M', time.gmtime(fileStat.st_mtime))


def fileProperty(filepath):
    return getFileMode(filepath) + '  ' + \
           getFilesNumber(filepath).rjust(4) + '  ' + \
           getUser(filepath).rjust(4) + '  ' + \
           getGroup(filepath).rjust(4) + '  ' + \
           getSize(filepath).rjust(12) + '  ' + \
           getLastTime(filepath).rjust(12) + '  ' + \
           os.path.basename(filepath)
