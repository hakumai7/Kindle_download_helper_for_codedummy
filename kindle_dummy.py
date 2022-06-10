"""
Note some download code from: https://github.com/sghctoma/bOOkp
Great Thanks
"""

import argparse
import html
import json
import logging
import os
import re
from http.cookies import SimpleCookie

import browser_cookie3
import requests
import urllib3

logger = logging.getLogger("kindle")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_OUT_DIR = "DOWNLOADS"

KINDLE_HEADER = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/1AE148",
}

CONTENT_TYPES = {
    "EBOK": "Ebook",
    "PDOC": "KindlePDoc",
}

KINDLE_URLS = {
    "cn": {
        "bookall": "https://www.amazon.cn/hz/mycd/myx#/home/content/booksAll",
        "download": "https://cde-ta-g7g.amazon.com/FionaCDEServiceEngine/FSDownloadContent?type={}&key={}&fsn={}&device_type={}&customerId={}&authPool=AmazonCN",
        "payload": "https://www.amazon.cn/hz/mycd/ajax",
    },
    "jp": {
        "bookall": "https://www.amazon.jp/hz/mycd/myx#/home/content/booksAll",
        "download": "https://cde-ta-g7g.amazon.com/FionaCDEServiceEngine/FSDownloadContent?type={}&key={}&fsn={}&device_type={}&customerId={}",
        "payload": "https://www.amazon.co.jp/hz/mycd/ajax",
    },
    "com": {
        "bookall": "https://www.amazon.com/hz/mycd/myx#/home/content/booksAll",
        "download": "https://cde-ta-g7g.amazon.com/FionaCDEServiceEngine/FSDownloadContent?type={}&key={}&fsn={}&device_type={}&customerId={}",
        "payload": "https://www.amazon.com/hz/mycd/ajax",
    },
}


class Kindle:
    def __init__(
        self, csrf_token, domain="cn", out_dir=DEFAULT_OUT_DIR, cut_length=100
    ):
        self.session = self.make_session()
        self.urls = KINDLE_URLS[domain]
        self.csrf_token = csrf_token
        self.total_to_download = 0
        self.out_dir = out_dir
        self.cut_length = cut_length

    def set_cookie_from_string(self, cookie_string):
        cj = self._parse_kindle_cookie(cookie_string)
        self.set_cookie(cj)

    def set_cookie(self, cookiejar):
        if not cookiejar:
            raise Exception("Please make sure your amazon cookie is right")
        self.session.cookies = cookiejar

    def set_cookie_from_browser(self):
        self.set_cookie(browser_cookie3.load())

    @staticmethod
    def _parse_kindle_cookie(kindle_cookie):
        cookie = SimpleCookie()
        cookie.load(kindle_cookie)
        cookies_dict = {}
        cookiejar = None
        for key, morsel in cookie.items():
            cookies_dict[key] = morsel.value
            cookiejar = requests.utils.cookiejar_from_dict(
                cookies_dict, cookiejar=None, overwrite=True
            )
        return cookiejar

    def _get_csrf_token(self):
        """
        TODO: I do not know why I have to get csrf token in the page not in this way
        maybe figure out why in the future
        """
        r = self.session.get(
            "https://www.amazon.cn/hz/mycd/digital-console/deviceprivacycentre"
        )
        match = re.search(r'var csrfToken = "(.*)";', r.text)
        if not match:
            raise Exception("There's not csrf token here, please check")
        return match.group(1)

    def get_devices(self):
        payload = {"param": {"GetDevices": {}}}
        r = self.session.post(
            self.urls["payload"],
            data={
                "data": json.dumps(payload),
                "csrfToken": self.csrf_token,
            },
        )
        devices = r.json()
        if devices.get("error"):
            # help user open it directly.
            import webbrowser

            try:
                logger.info(
                    "Opening the url to get cookie...You can wait for the page to finish loading and retry"
                )
                webbrowser.open(self.urls["bookall"])
            except:
                # just do nothing
                pass
            raise Exception(
                f"Error: {devices.get('error')}, please visit {self.urls['bookall']} to revoke the csrftoken and cookie"
            )
        devices = r.json()["GetDevices"]["devices"]
        return [device for device in devices if "deviceSerialNumber" in device]

    def get_all_books(self, filetype="EBOK"):
        """
        TODO: refactor this function
        """
        startIndex = 0
        batchSize = 100
        payload = {
            "param": {
                "OwnershipData": {
                    "sortOrder": "DESCENDING",
                    "sortIndex": "DATE",
                    "startIndex": startIndex,
                    "batchSize": batchSize,
                    "contentType": CONTENT_TYPES[filetype],
                    "itemStatus": ["Active"],
                }
            }
        }

        if filetype == "EBOK":
            payload["param"]["OwnershipData"].update(
                {
                    "originType": ["Purchase"],
                }
            )
        else:
            batchSize = 18
            payload["param"]["OwnershipData"].update(
                {
                    "batchSize": batchSize,
                    "isExtendedMYK": False,
                }
            )

        books = []
        while True:
            r = self.session.post(
                self.urls["payload"],
                data={"data": json.dumps(payload), "csrfToken": self.csrf_token},
            )
            r.raise_for_status()
            result = r.json()
            items = result["OwnershipData"]["items"]
            if filetype == "PDOC":
                for item in items:
                    item["title"] = html.unescape(item["title"])
                    item["authors"] = html.unescape(item.pop("author", ""))

            books.extend(items)

            if result["OwnershipData"]["hasMoreItems"]:
                startIndex += batchSize
                payload["param"]["OwnershipData"]["startIndex"] = startIndex
            else:
                break
        return books

    def make_session(self):
        session = requests.Session()
        session.headers.update(KINDLE_HEADER)
        return session

    def download_one_book(self, book, device, index, filetype="EBOK"):
        name = book["title"]
        try:
            download_url = self.urls["download"].format(
                filetype,
                book["asin"],
                device["deviceSerialNumber"],
                device["deviceType"],
                device["customerId"],
            )
            r = self.session.get(download_url, verify=False, stream=True)
            r.raise_for_status()
            if len(name) > self.cut_length:
                name = name[: self.cut_length - 5] + name[-5:]
            total_size = r.headers["Content-length"]
            out = os.path.join(self.out_dir, name)
            logger.info(
                f"({index + 1}/{self.total_to_download})downloading {name} {total_size} bytes"
            )
            with open(out, "wb") as f:
                for chunk in r.iter_content(chunk_size=512):
                    f.write(chunk)
            logger.info(f"{name} downloaded")
        except Exception as e:
            logger.error(str(e))
            logger.error(f"{name} download failed")

    def download_books(self, start_index=0, filetype="EBOK"):
        # use default device
        device = self.get_devices()[0]
        books = self.get_all_books(filetype=filetype)
        self.total_to_download = len(books)
        if start_index > 0:
            print(f"resuming the download {start_index + 1}/{self.total_to_download}")
        index = start_index
        for book in books[start_index:]:
            self.download_one_book(book, device, index, filetype)
            index += 1

        logger.info(
            "\n\nAll done!\nNow you can use apprenticeharper's DeDRM tools "
            "(https://github.com/apprenticeharper/DeDRM_tools)\n"
            "with the following serial number to remove DRM: "
            + device["deviceSerialNumber"]
        )
        with open(os.path.join(self.out_dir, "key.txt"), "w") as f:
            f.write(f"Key is: {device['deviceSerialNumber']}")


if __name__ == "__main__":
    csrfToken = os.getenv('csrfToken')
    domain = os.getenv('domain')
    startindex = os.getenv('startindex')
    downloadfiletype = os.getenv('downloadfiletype')

    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())

    cut_length=100
    if not os.path.exists(DEFAULT_OUT_DIR):
        os.makedirs(DEFAULT_OUT_DIR)
    kindle = Kindle(
        csrf_token, domain, DEFAULT_OUT_DIR, cut_length
    )
    if startindex is None or startindex=='':
        startindex=1
    if not downloadfiletype in ['EBOK','PDOC']:
        downloadfiletype='EBOK'
    kindle.download_books(start_index=startindex - 1, filetype=downloadfiletype)
