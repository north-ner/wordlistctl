#!/usr/bin/env python3
# -*- coding: latin-1 -*- ######################################################
#                                                                              #
# wordlistctl - Fetch, install and search wordlist archives from websites and  #
# torrent peers.                                                               #
#                                                                              #
# DESCRIPTION                                                                  #
# Script to fetch, install, update and search wordlist archives from websites  #
# offering wordlists with more than 2900 wordlists available.                  #
#                                                                              #
# AUTHORS                                                                      #
# sepehrdad.dev@gmail.com                                                      #
# noptrix@nullsecurity.net                                                     #
#                                                                              #
#                                                                              #
################################################################################


# Load Deps
import warnings
import sys
import os
import getopt
import requests
import re
import time
import json
from gzip import GzipFile
from bz2 import BZ2File
from lzma import LZMAFile
from hashlib import md5
from shutil import copyfileobj
from concurrent.futures import ThreadPoolExecutor

try:
    import libtorrent
    import libarchive
    from rarfile import RarFile
    from bs4 import BeautifulSoup
    from termcolor import colored
except Exception as ex:
    print(f"Error while loading dependencies: {str(ex)}", file=sys.stderr)
    exit(-1)


version_number: str = "0.8.8-dev"
project_name: str = "wordlistctl"
organization: str = "blackarch.org"

wordlist_path: str = "/usr/share/wordlists"
wordlist_repo: dict = {}

selected_category: str = ""
decompress_archive: bool = False
remove_archive: bool = False
prefer_http: bool = False
torrent_dl: bool = True

parallel_executer = None
max_parallel: int = 5
torrent_session = None
useragent_string: str = "Mozilla/5.0 (X11; Linux x86_64; rv:68.0) Gecko/20100101 Firefox/68.0"
chunk_size: int = 1024
skip_integrity_check: bool = False
max_retry: int = 3


def err(string: str) -> None:
    print(colored("[-]", "red", attrs=["bold"]), f" {string}", file=sys.stderr)


def warn(string: str) -> None:
    print(colored("[!]", "yellow", attrs=["bold"]), f" {string}")


def info(string: str) -> None:
    print(colored("[*]", "blue", attrs=["bold"]), f" {string}")


def success(string: str) -> None:
    print(colored("[+]", "green", attrs=["bold"]), f" {string}")


def usage() -> None:
    str_usage: str = "usage:\n\n"
    str_usage += f"  {project_name} -f <arg> [options] | -s <arg> [options] | -S <arg> | <misc>\n\n"
    str_usage += "options:\n\n"
    str_usage += "  -f <num>   - download chosen wordlist - ? to list wordlists with id\n"
    str_usage += "  -d <dir>   - wordlists base directory (default: /usr/share/wordlists)\n"
    str_usage += "  -c <num>   - change wordlists category - ? to list wordlists categories\n"
    str_usage += "  -s <regex> - wordlist to search using <regex> in base directory\n"
    str_usage += "  -S <regex> - wordlist to search using <regex> in sites\n"
    str_usage += "  -h         - prefer http\n"
    str_usage += "  -X         - decompress wordlist\n"
    str_usage += "  -F <str>   - list wordlists in categories given\n"
    str_usage += "  -r         - remove compressed file after decompression\n"
    str_usage += "  -t <num>   - max parallel downloads (default: 5)\n\n"
    str_usage += "misc:\n\n"
    str_usage += "  -T         - disable torrent download\n"
    str_usage += "  -A <str>   - set useragent string\n"
    str_usage += "  -I         - skip integrity checks\n"
    str_usage += f"  -V         - print version of {project_name} and exit\n"
    str_usage += "  -H         - print this help and exit\n\n"
    str_usage += "example:\n\n"
    str_usage += "  # download and decompress all wordlists and remove archive\n"
    str_usage += f"  $ {project_name} -f 0 -Xr\n\n"
    str_usage += "  # download all wordlists in username category\n"
    str_usage += f"  $ {project_name} -f 0 -c 0\n\n"
    str_usage += "  # list all wordlists in password category with id\n"
    str_usage += f"  $ {project_name} -f ? -c 1\n\n"
    str_usage += "  # download and decompress all wordlists in misc category\n"
    str_usage += f"  $ {project_name} -f 0 -c 4 -X\n\n"
    str_usage += "  # download all wordlists in filename category using 20 threads\n"
    str_usage += f"  $ {project_name} -c 3 -f 0 -t 20\n\n"
    str_usage += "  # download wordlist with id 2 to \"~/wordlists\" directory using http\n"
    str_usage += f"  $ {project_name} -f 2 -d ~/wordlists -h\n\n"
    str_usage += "  # print wordlists in username and password categories\n"
    str_usage += f"  $ {project_name} -F username,password\n\n"
    str_usage += "  # download all wordlists with using noleak useragent\n"
    str_usage += f"  $ {project_name} -f 0 -A \"noleak\"\n\n"
    str_usage += "notes:\n\n"
    str_usage += "  * Wordlist's id are relative to the category that is chosen\n"
    str_usage += "    and are not global, so by changing the category Wordlist's\n"
    str_usage += "    id changes. E.g.: -f 1337 != -c 1 -f 1337. use -f ? -c 1\n"
    str_usage += "    to get the real id for a given password list.\n\n"
    str_usage += "  * In order to disable color terminal set ANSI_COLORS_DISABLED\n"
    str_usage += "    enviroment variable to 1.\n"
    str_usage += f"    E.g.: ANSI_COLORS_DISABLED=1 {project_name} -H\n"

    print(str_usage)


def version() -> None:
    print(f"{project_name} v{version_number}")


def banner():
    print(colored(f"--==[ {project_name} by {organization} ]==--\n",
                  "red", attrs=["bold"]))


def decompress(filepath: str) -> None:
    filename: str = os.path.basename(filepath)
    info(f"decompressing {filename}")
    if re.fullmatch(r"^.*\.(rar)$", filename.lower()):
        os.chdir(os.path.dirname(filepath))
        infile = RarFile(filepath)
        infile.extractall()
    elif re.fullmatch(r"^.*\.(zip|7z|tar|tar.gz|tar.xz|tar.bz2)$", filename.lower()):
        os.chdir(os.path.dirname(filepath))
        libarchive.extract_file(filepath)
    else:
        if re.fullmatch(r"^.*\.(gz)$", filepath.lower()):
            infile = GzipFile(filepath, "rb")
        elif re.fullmatch(r"^.*\.(bz|bz2)$", filepath.lower()):
            infile = BZ2File(filepath, "rb")
        elif re.fullmatch(r"^.*\.(lzma|xz)$", filepath.lower()):
            infile = LZMAFile(filepath, "rb")
        else:
            raise ValueError("unknown file type")
        outfile = open(os.path.splitext(filepath)[0], "wb")
        copyfileobj(infile, outfile)
        outfile.close()
    success(f"decompressing {filename} completed")


def clean(filename: str) -> None:
    if remove_archive:
        remove(filename)


def remove(filename: str) -> None:
    try:
        os.remove(filename)
    except:
        pass


def resolve_mediafire(url: str) -> str:
    try:
        page = requests.head(url,
                             headers={"User-Agent": ""},
                             allow_redirects=True)
        if page.url != url and "text/html" not in page.headers["Content-Type"]:
            return page.url
        else:
            page = requests.get(
                url, headers={"User-Agent": ""}, allow_redirects=True)
            html = BeautifulSoup(page.text, "html.parser")
            for i in html.find_all('a', {"class": "input"}):
                if str(i.text).strip().startswith("Download ("):
                    return i["href"]
        return url
    except:
        return ''


def resolve_sourceforge(url: str) -> str:
    try:
        rq = requests.get(url, stream=True,
                          headers={"User-Agent": ""},
                          allow_redirects=True)
        return rq.url
    except:
        return ''


def resolve(url: str) -> str:
    resolver = None
    resolved = ""
    if str(url).startswith("http://downloads.sourceforge.net/"):
        resolver = resolve_sourceforge
    elif str(url).startswith("http://www.mediafire.com/file/"):
        resolver = resolve_mediafire
    if resolver is None:
        resolved = url
    else:
        count = 0
        while (resolved == "") and (count < 10):
            resolved = resolver(url)
            time.sleep(10)
            count += 1
    return resolved


def to_readable_size(size: float) -> str:
    units: dict = {0: 'bytes',
                   1: 'Kbytes',
                   2: 'Mbytes',
                   3: 'Gbytes',
                   4: 'Tbytes'}
    i: int = 0
    while size > 1000:
        size /= 1000
        i += 1
    return f"{size:.2f} {units[i]}"


def integrity_check(checksum: str, path: str) -> None:
    global chunk_size
    global skip_integrity_check
    filename = os.path.basename(path)
    info(f"checking {filename} integrity")
    if checksum == 'SKIP' or skip_integrity_check:
        warn(f"{filename} integrity check -- skipping")
    hashagent = md5()
    fp = open(path, 'rb')
    while True:
        data = fp.read(chunk_size)
        if not data:
            break
        hashagent.update(data)
    if checksum != hashagent.hexdigest():
        raise IOError(f"{filename} integrity check -- failed")


def fetch_file(url: str, path: str) -> None:
    global chunk_size
    filename: str = os.path.basename(path)
    if check_file(path):
        warn(f"{filename} already exists -- skipping")
    else:
        info(f"downloading {filename} to {path}")
        dlurl = resolve(url)
        rq = requests.get(dlurl, stream=True,
                          headers={"User-Agent": useragent_string})
        fp = open(path, "wb")
        for data in rq.iter_content(chunk_size=chunk_size):
            fp.write(data)
        fp.close()
        success(f"downloading {filename} completed")


def fetch_torrent(url: str, path: str) -> None:
    global torrent_session
    global torrent_dl
    if torrent_session is None:
        torrent_session = libtorrent.session(
            {"listen_interfaces": "0.0.0.0:6881"})
        torrent_session.start_dht()
    magnet = False
    if str(url).startswith("magnet:?"):
        magnet = True
    handle = None
    if magnet:
        handle = libtorrent.add_magnet_uri(
            torrent_session, url,
            {
                "save_path": os.path.dirname(path),
                "storage_mode": libtorrent.storage_mode_t(2),
                "paused": False,
                "auto_managed": True,
                "duplicate_is_error": True
            }
        )
        info("downloading metadata\n")
        while not handle.has_metadata():
            time.sleep(0.1)
        success("downloaded metadata")
    else:

        if not torrent_dl:
            return
        if os.path.isfile(path):
            handle = torrent_session.add_torrent(
                {
                    "ti": libtorrent.torrent_info(path),
                    "save_path": os.path.dirname(path)
                }
            )
            remove(path)
        else:
            err(f"{path} not found")
            exit(-1)
    outfilename = f"{os.path.dirname(path)}/{handle.name()}"
    info(f"downloading {handle.name()} to {outfilename}")
    while not handle.is_seed():
        time.sleep(0.1)
    torrent_session.remove_torrent(handle)
    success(f"downloading {handle.name()} completed")
    decompress(outfilename)


def download_wordlist(config: dict, wordlistname: str, category: str) -> None:
    filename: str = ""
    file_directory: str = ""
    file_path: str = ""
    check_dir(f"{wordlist_path}/{category}")
    file_directory = f"{wordlist_path}/{category}"

    for _ in range(0, max_retry + 1):
        try:

            urls: list = config["url"]
            urls.sort()
            url: str = ""
            if prefer_http:
                url = urls[0]
            else:
                url = urls[-1]
            filename = url.split('/')[-1]
            file_path = f"{file_directory}/{filename}"
            csum = config["sum"][config["url"].index(url)]
            if url.startswith("http"):
                fetch_file(url, file_path)
                integrity_check(csum, file_path)
                decompress(file_path)
            else:
                if url.replace("torrent+", "").startswith("magnet:?"):
                    fetch_torrent(url.replace("torrent+", ""), file_path)
                else:
                    fetch_file(url.replace("torrent+", ""), file_path)
                    integrity_check(csum, file_path)
                    fetch_torrent(url, file_path)
            break
        except Exception as ex:
            err(f"Error while downloading {wordlistname}: {str(ex)}")
            remove(file_path)


def download_wordlists(code: str) -> None:
    global wordlist_repo
    global parallel_executer

    check_dir(wordlist_path)

    wordlist_id: int = to_int(code)
    wordlists_count: int = 0
    for i in wordlist_repo.keys():
        wordlists_count += wordlist_repo[i]["count"]

    lst: dict = {}

    try:
        if (wordlist_id >= wordlists_count + 1) or wordlist_id < 0:
            raise IndexError(f"{code} is not a valid wordlist id")
        elif wordlist_id == 0:
            if selected_category == "":
                lst = wordlist_repo
            else:
                lst[selected_category] = wordlist_repo[selected_category]
        elif selected_category != "":
            lst[selected_category] = {
                "files": [wordlist_repo[selected_category]["files"][wordlist_id - 1]]
            }
        else:
            cat: str = ""
            count: int = 0
            wid: int = 0
            for i in wordlist_repo.keys():
                count += wordlist_repo[i]["count"]
                if (wordlist_id - 1) < (count):
                    cat = i
                    break
            wid = (wordlist_id - 1) - count
            lst[cat] = {"files": [wordlist_repo[cat]["files"][wid]]}
        for i in lst.keys():
            for j in lst[i]["files"]:
                parallel_executer.submit(download_wordlist, j, j["name"], i)
        parallel_executer.shutdown(wait=True)
    except Exception as ex:
        err(f"Error unable to download wordlist: {str(ex)}")


def print_wordlists(categories: str = "") -> None:
    global wordlist_repo
    if categories == "":
        lst: list = []
        success("available wordlists:\n")
        print("    > 0  - all wordlists")
        if selected_category != "":
            lst = wordlist_repo[selected_category]["files"]
        else:
            for i in wordlist_repo.keys():
                lst += wordlist_repo[i]["files"]

        for i in lst:
            id = lst.index(i) + 1
            name = i["name"]
            compsize = to_readable_size(i["size"][0])
            decompsize = to_readable_size(i["size"][1])
            print(f"    > {id}  - {name} ({compsize}, {decompsize})")
        print("")
    else:
        categories_list: set = set([i.strip() for i in categories.split(',')])
        for i in categories_list:
            if i not in wordlist_repo.keys():
                err(f"category {i} is unavailable")
                exit(-1)
        for i in categories_list:
            success(f"{i}:")
            for j in wordlist_repo[i]["files"]:
                name = j["name"]
                compsize = to_readable_size(j["size"][0])
                decompsize = to_readable_size(j["size"][1])
                print(f"    > {name} ({compsize}, {decompsize})")
            print("")


def search_dir(regex: str) -> None:
    global wordlist_path
    count: int = 0
    try:
        for root, _, files in os.walk(wordlist_path):
            for f in files:
                if re.match(regex, f):
                    info(f"wordlist found: {os.path.join(root, f)}")
                    count += 1
        if count == 0:
            err("wordlist not found")
    except:
        pass


def search_sites(regex: str) -> None:
    count: int = 0
    lst: list = []
    info(f"searching for {regex} in repo.json\n")
    try:
        if selected_category != "":
            lst = wordlist_repo[selected_category]["files"]
        else:
            for i in wordlist_repo.keys():
                lst += wordlist_repo[i]["files"]

        for i in lst:
            name = i["name"]
            id = lst.index(i) + 1
            if re.match(regex, name):
                success(f"wordlist {name} found: id={id}")
                count += 1

        if count == 0:
            err("no wordlist found")
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        err(f"Error while searching: {str(ex)}")


def check_dir(dir_name: str) -> None:
    try:
        if os.path.isdir(dir_name):
            pass
        else:
            info(f"creating directory {dir_name}")
            os.mkdir(dir_name)
    except Exception as ex:
        err(f"unable to create directory: {str(ex)}")
        exit(-1)


def check_file(path: str) -> bool:
    return os.path.isfile(str(path))


def change_category(code: str) -> None:
    global selected_category
    global wordlist_repo
    category_id: int = to_int(code)
    try:
        if (category_id >= list(wordlist_repo.keys()).__len__()) or category_id < 0:
            raise IndexError(f"{code} is not a valid category id")
        selected_category = list(wordlist_repo.keys())[category_id]
    except Exception as ex:
        err(f"Error while changing category: {str(ex)}")
        exit(-1)


def print_categories() -> None:
    index: int = 0
    success("available wordlists category:\n")
    for i in wordlist_repo.keys():
        count = wordlist_repo[i]["count"]
        compsize = to_readable_size(wordlist_repo[i]["size"][0])
        decompsize = to_readable_size(wordlist_repo[i]["size"][1])
        print(f"    > {index}  - {i} ({count} lsts, {compsize}, {decompsize})")
        index += 1
    print("")


def load_config() -> None:
    global wordlist_repo
    configfile: str = f"{os.path.dirname(os.path.realpath(__file__))}/repo.json"
    if wordlist_repo.__len__() <= 0:
        try:
            if not os.path.isfile(configfile):
                raise FileNotFoundError("Config file not found")
            wordlist_repo = json.load(open(configfile, 'r'))
        except Exception as ex:
            err(f"Error while loading config files: {str(ex)}")
            exit(-1)


def to_int(string: str) -> int:
    try:
        return int(string)
    except:
        err(f"{string} is not a valid number")
        exit(-1)


def arg_parse(argv: list) -> tuple:
    global wordlist_path
    global decompress_archive
    global remove_archive
    global prefer_http
    global max_parallel
    global torrent_dl
    global useragent_string
    global skip_integrity_check
    function = None
    arguments = None
    opFlag: int = 0

    try:
        opts, _ = getopt.getopt(argv[1:], "IHNVXThrd:c:f:s:S:t:F:A:")

        if opts.__len__() <= 0:
            function = usage
            return function, None

        for opt, arg in opts:
            if opFlag and re.fullmatch(r"^-([VfsSF])", opt):
                raise getopt.GetoptError("multiple operations selected")
            if opt == "-H":
                function = usage
                return function, None
            elif opt == "-V":
                function = version
                opFlag += 1
            elif opt == "-d":
                dirname = os.path.abspath(arg)
                check_dir(dirname)
                wordlist_path = dirname
            elif opt == "-f":
                if arg == '?':
                    function = print_wordlists
                else:
                    function = download_wordlists
                    arguments = arg
                opFlag += 1
            elif opt == "-s":
                function = search_dir
                arguments = arg
                opFlag += 1
            elif opt == "-X":
                decompress_archive = True
            elif opt == "-r":
                remove_archive = True
            elif opt == "-T":
                torrent_dl = False
            elif opt == "-I":
                skip_integrity_check = True
            elif opt == "-A":
                useragent_string = arg
            elif opt == "-S":
                function = search_sites
                arguments = arg
                opFlag += 1
            elif opt == "-c":
                if arg == '?':
                    function = print_categories
                    return function, None
                else:
                    load_config()
                    change_category(arg)
            elif opt == "-h":
                prefer_http = True
            elif opt == "-t":
                max_parallel = to_int(arg)
                if max_parallel <= 0:
                    raise Exception("threads number can't be less than 1")
            elif opt == "-F":
                function = print_wordlists
                arguments = arg
                opFlag += 1
    except getopt.GetoptError as ex:
        err(f"Error while parsing arguments: {str(ex)}")
        warn("-H for help and usage")
        exit(-1)
    except Exception as ex:
        err(f"Error while parsing arguments: {str(ex)}")
        exit(-1)
    return function, arguments


def main(argv: list) -> int:
    global max_parallel
    global parallel_executer
    banner()

    function, arguments = arg_parse(argv)

    try:
        if function not in [version, usage]:
            load_config()
        if parallel_executer is None:
            parallel_executer = ThreadPoolExecutor(max_parallel)
        if function is not None:
            if arguments is not None:
                function(arguments)
            else:
                function()
        else:
            raise getopt.GetoptError("no operation selected")
        return 0
    except getopt.GetoptError as ex:
        err(f"Error while running operation: {str(ex)}")
        warn("-H for help and usage")
        return -1
    except Exception as ex:
        err(f"Error while running operation: {str(ex)}")
        return -1


if __name__ == "__main__":
    warnings.simplefilter('ignore')
    sys.exit(main(sys.argv))
