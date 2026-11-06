"""
network-related helper
"""

from typing import Any

from .utils.contact_rest import RESTContact


class NetworkRel:
    def __init__(self, burl: str):
        self.burl = burl

    def execute_method_and_return_custom_msg(
        self,
        method: str,
        dest: str | None = None,
        params: dict = {},
        payload: dict = {},
        success: Any = True,
        failure: Any = True,
    ):
        self.rest = RESTContact(self.burl)

        if method != "download" and method in ["get", "put", "post", "del"]:
            out = self.rest._call_url(method=method, params=params, payload=payload)
            if out[0] == 200 and not out[1].get("resp_text"):
                return success
            return failure

        elif method == "download":
            if isinstance(dest, str):
                out = self.rest._download_url(dest=dest, params=params)
                if out[0] == 200 and not out[1].get("resp_text"):
                    return success
                return failure
            return failure
        else:
            return failure
