"""Best-effort discovery of the Agent's current public IPv4 address."""
from __future__ import annotations

import ipaddress
import os
import urllib.request
from typing import Any

_DEFAULT_URLS=(
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
)


def _urls()->tuple[str,...]:
    raw=str(os.environ.get("CAPIVARA_PUBLIC_IPV4_URLS") or "").strip()
    if not raw:return _DEFAULT_URLS
    values=[]
    for value in raw.split(","):
        url=value.strip()
        if url.startswith("https://") and url not in values:values.append(url)
    return tuple(values[:4]) or _DEFAULT_URLS


def observe_public_ipv4(*,timeout:float=4.0)->dict[str,Any]:
    errors=[]
    for url in _urls():
        try:
            request=urllib.request.Request(url,headers={"User-Agent":"Capivara-Agent/2"})
            with urllib.request.urlopen(request,timeout=max(1.0,min(float(timeout),10.0))) as response:
                text=response.read(128).decode("ascii",errors="ignore").strip()
            address=ipaddress.ip_address(text)
            if address.version!=4 or not address.is_global:
                raise ValueError("endpoint did not return a global IPv4 address")
            return {"status":"observed","public_ipv4":str(address),"source":url}
        except Exception as exc:
            errors.append(str(exc)[:200])
    return {"status":"unavailable","public_ipv4":None,"source":None,"error":"; ".join(errors[:2])[:400] or "public IPv4 lookup failed"}


__all__=["observe_public_ipv4"]
