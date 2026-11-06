"""
contact_rest util for CPackages.
Uses requests lib to send REST-API based requests.


Basic API usage:

rest = RESTContact(\"https://google.com\")
get_out = rest.get_req() # tuple (format: status_code, json_parsed)
download_out = rest.download_req(dest=\"file.html\")

print(get_out[1]) # Print the json
print(download_out)
---

However if there is a Exception, the json output will be: resp.status_code (int), {\"resp_text\": resp.text}
"""

from typing import Any
import requests as r


class RESTContact:
    def __init__(
        self, base_url: str = "https://example.com"
    ):  # Please do not leave the base_url EMPTY (or not specified)
        self.burl = base_url

    def _call_url(
        self,
        method: str,
        payload: dict = {},
        params: dict = {},
    ) -> tuple[int, dict[Any | str]]:  # pyright: ignore
        match method.lower():
            case "get":
                resp = r.get(self.burl, params=params)
                try:
                    return (resp.status_code, resp.json())
                except Exception:
                    shorted_text = (
                        f"{resp.text[:500]}..." if len(resp.text) > 500 else resp.text
                    )
                    return (resp.status_code, {"resp_text": shorted_text})
            case "post":
                resp = r.post(self.burl, json=payload, params=params)
                try:
                    return (resp.status_code, resp.json())
                except Exception:
                    return (resp.status_code, {"resp_text": resp.text})
            case "put":
                resp = r.put(self.burl, json=payload, params=params)
                try:
                    return (resp.status_code, resp.json())
                except Exception:
                    return (resp.status_code, {"resp_text": resp.text})
            case "del":
                resp = r.delete(self.burl, json=payload, params=params)
                try:
                    return (resp.status_code, resp.json())
                except Exception:
                    return (resp.status_code, {"resp_text": resp.text})
            case _:
                return (
                    404,
                    {
                        "error": f"method {method.lower()} is an invalid method to call. (Maybe you're searching for download?)"
                    },
                )

    def _download_url(
        self,
        dest: str,
        params: dict = {},
        chunk_size: int = 8192,
    ) -> tuple[int, dict]:
        resp = r.get(self.burl, params=params, stream=True)
        try:
            if resp.status_code == 200:
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                return (resp.status_code, {"saved_to": dest})
            else:
                return (resp.status_code, {"resp_text": resp.text[:500]})
        except Exception as e:
            return (resp.status_code, {"error": str(e)})

    def get_req(
        self,
        params: dict = {},
    ) -> tuple[int, dict]:  # pyright: ignore
        out = self._call_url(
            method="get",
            params=params,
        )
        return out

    def post_req(self, payload: dict) -> tuple[int, dict]:
        out = self._call_url(method="post", payload=payload)
        return out

    def put_req(self, payload: dict) -> tuple[int, dict]:
        out = self._call_url(method="put", payload=payload)
        return out

    def del_req(self, params: dict = {}, payload: dict = {}) -> tuple[int, dict]:
        out = self._call_url(method="del", params=params, payload=payload)
        return out

    def download_req(self, dest: str, params: dict = {}) -> tuple[int, dict]:
        out = self._download_url(dest=dest, params=params)
        return out
