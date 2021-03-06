import os
import sys
import zlib
import shutil
import hashlib
import urllib
import xbmc
import xbmcaddon
import xbmcvfs
import struct
import random
from urlparse import urlparse
from httplib import HTTPConnection, OK

__addon__ = xbmcaddon.Addon()
__version__ = __addon__.getAddonInfo('version')
__scriptname__ = __addon__.getAddonInfo('name')

SVP_REV_NUMBER = 1543
CLIENTKEY = "SP,aerSP,aer %d &e(\xd7\x02 %s %s"
RETRY = 3


class AppURLopener(urllib.FancyURLopener):
    version = "XBMC(Kodi)-subtitle/%s" % __version__  # cf block default ua


urllib._urlopener = AppURLopener()


def log(module, msg):
    xbmc.log((u"%s::%s - %s" % (__scriptname__, module, msg,)
              ).encode('utf-8'), level=xbmc.LOGDEBUG)


def grapBlock(f, offset, size):
    f.seek(offset, 0)
    return f.read(size)


def getBlockHash(f, offset):
    return hashlib.md5(grapBlock(f, offset, 4096)).hexdigest()


def genFileHash(fpath):
    f = xbmcvfs.File(fpath)
    ftotallen = f.size()
    if ftotallen < 8192:
        f.close()
        return ""
    offset = [4096, ftotallen / 3 * 2, ftotallen / 3, ftotallen - 8192]
    hash = ";".join(getBlockHash(f, i) for i in offset)
    f.close()
    return hash


def getShortNameByFileName(fpath):
    fpath = os.path.basename(fpath).rsplit(".", 1)[0]
    fpath = fpath.lower()

    for stop in ["blueray", "bluray", "dvdrip", "xvid", "cd1", "cd2", "cd3", "cd4", "cd5", "cd6", "vc1", "vc-1", "hdtv", "1080p", "720p", "1080i", "x264", "stv", "limited", "ac3", "xxx", "hddvd"]:
        i = fpath.find(stop)
        if i >= 0:
            fpath = fpath[:i]

    for c in "[].-#_=+<>,":
        fpath = fpath.replace(c, " ")

    return fpath.strip()


def getShortName(fpath):
    for i in range(3):
        shortname = getShortNameByFileName(os.path.basename(fpath))
        if not shortname:
            fpath = os.path.dirname(fpath)
        else:
            return shortname


def genVHash(svprev, fpath, fhash):
    """
    the clientkey is not avaliable now, but we can get it by reverse engineering splayer.exe
    to get the clientkey from splayer.exe:
    f = open("splayer","rb").read()
    i = f.find(" %s %s%s")"""
    global CLIENTKEY
    if CLIENTKEY:
        #sprintf_s( buffx, 4096, CLIENTKEY , SVP_REV_NUMBER, szTerm2, szTerm3, uniqueIDHash);
        vhash = hashlib.md5(CLIENTKEY % (svprev, fpath, fhash)).hexdigest()
    else:
        #sprintf_s( buffx, 4096, "un authiority client %d %s %s %s", SVP_REV_NUMBER, fpath.encode("utf8"), fhash.encode("utf8"), uniqueIDHash);
        vhash = hashlib.md5("un authiority client %d %s %s " %
                            (svprev, fpath, fhash)).hexdigest()
    return vhash


def urlopen(url, svprev, formdata):
    ua = "SPlayer Build %d" % svprev
    # prepare data
    # generate a random boundary
    boundary = "----------------------------" + "%x" % random.getrandbits(48)
    data = []
    for item in formdata:
        data.append("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" +
                    item[0] + "\"\r\n\r\n" + item[1] + "\r\n")
    data.append("--" + boundary + "--\r\n")
    data = "".join(data)
    cl = str(len(data))

    r = urlparse(url)
    h = HTTPConnection(r.hostname)
    h.connect()
    h.putrequest("POST", r.path, skip_host=True, skip_accept_encoding=True)
    h.putheader("User-Agent", ua)
    h.putheader("Host", r.hostname)
    h.putheader("Accept", "*/*")
    h.putheader("Content-Length", cl)
    h.putheader("Expect", "100-continue")
    h.putheader("Content-Type", "multipart/form-data; boundary=" + boundary)
    h.endheaders()

    h.send(data)

    resp = h.getresponse()
    if resp.status != OK:
        raise Exception("HTTP response " +
                        str(resp.status) + ": " + resp.reason)
    return resp


def downloadSubs(fpath, lang):
    global SVP_REV_NUMBER
    global RETRY
    pathinfo = fpath
    if os.path.sep != "\\":
        #*nix
        pathinfo = "E:\\" + pathinfo.replace(os.path.sep, "\\")
    filehash = genFileHash(fpath)
    shortname = getShortName(fpath)
    vhash = genVHash(SVP_REV_NUMBER, fpath.encode("utf-8"), filehash)
    formdata = []
    formdata.append(("pathinfo", pathinfo.encode("utf-8")))
    formdata.append(("filehash", filehash))
    if vhash:
        formdata.append(("vhash", vhash))
    formdata.append(("shortname", shortname.encode("utf-8")))
    if lang != "chn":
        formdata.append(("lang", lang))

    for server in ["www", "svplayer", "splayer1", "splayer2", "splayer3", "splayer4", "splayer5", "splayer6", "splayer7", "splayer8", "splayer9"]:
        for schema in ["http", "https"]:
            theurl = schema + "://" + server + ".shooter.cn/api/subapi.php"
            for i in range(1, RETRY + 1):
                try:
                    log(sys._getframe().f_code.co_name,
                        "Trying %s (retry %d)" % (theurl, i))
                    handle = urlopen(theurl, SVP_REV_NUMBER, formdata)
                    resp = handle.read()
                    if len(resp) > 1024:
                        return resp
                    else:
                        return ''
                except Exception, e:
                    log(sys._getframe().f_code.co_name,
                        "Failed to access %s" % (theurl))
    return ''


class Package(object):
    def __init__(self, s):
        self.parse(s)

    def parse(self, s):
        c = s.read(1)
        self.SubPackageCount = struct.unpack("!B", c)[0]
        log(sys._getframe().f_code.co_name, "SubPackageCount: %d" %
            (self.SubPackageCount))
        self.SubPackages = []
        for i in range(self.SubPackageCount):
            try:
                sub = SubPackage(s)
            except:
                break
            self.SubPackages.append(sub)


class SubPackage(object):
    def __init__(self, s):
        self.parse(s)

    def parse(self, s):
        c = s.read(8)
        self.PackageLength, self.DescLength = struct.unpack("!II", c)
        self.DescData = s.read(self.DescLength)
        c = s.read(5)
        self.FileDataLength, self.FileCount = struct.unpack("!IB", c)
        self.Files = []
        for i in range(self.FileCount):
            file = SubFile(s)
            self.Files.append(file)


class SubFile(object):
    def __init__(self, s):
        self.parse(s)

    def parse(self, s):
        c = s.read(8)
        self.FilePackLength, self.ExtNameLength = struct.unpack("!II", c)
        self.ExtName = s.read(self.ExtNameLength)
        c = s.read(4)
        self.FileDataLength = struct.unpack("!I", c)[0]
        self.FileData = s.read(self.FileDataLength)
        if self.FileData.startswith("\x1f\x8b"):
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            self.FileData = d.decompress(self.FileData)


def CalcFileHash(a):
    def b(j):
        g = ""
        for i in range(len(j)):
            h = ord(j[i])
            if (h + 47 >= 126):
                g += chr(ord(" ") + (h + 47) % 126)
            else:
                g += chr(h + 47)
        return g

    def d(g):
        h = ""
        for i in range(len(g)):
            h += g[len(g) - i - 1]
        return h

    def c(j, h, g, f):
        p = len(j)
        return j[p - f + g - h:p - f + g] + j[p - f:p - f + g - h] + j[p - f + g:p] + j[0:p - f]
    if len(a) > 32:
        charString = a[1:len(a)]
        result = {
            'o': lambda: b(c(charString, 8, 17, 27)),
            'n': lambda: b(d(c(charString, 6, 15, 17))),
            'm': lambda: d(c(charString, 6, 11, 17)),
            'l': lambda: d(b(c(charString, 6, 12, 17))),
            'k': lambda: c(charString, 14, 17, 24),
            'j': lambda: c(b(d(charString)), 11, 17, 27),
            'i': lambda: c(d(b(charString)), 5, 7, 24),
            'h': lambda: c(b(charString), 12, 22, 30),
            'g': lambda: c(d(charString), 11, 15, 21),
            'f': lambda: c(charString, 14, 17, 24),
            'e': lambda: c(charString, 4, 7, 22),
            'd': lambda: d(b(charString)),
            'c': lambda: b(d(charString)),
            'b': lambda: d(charString),
            'a': lambda: b(charString)
        }[a[0]]()
        return result
    return a
