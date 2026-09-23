#!/usr/bin/env python3
"""Minimal Steam/Valve A2S client used by the customer connection test."""
from __future__ import annotations

import socket
import struct
from typing import Any

_HEADER=b"\xff\xff\xff\xff"
_SPLIT=b"\xff\xff\xff\xfe"
_INFO_REQUEST=_HEADER+b"TSource Engine Query\x00"
_RULES_REQUEST=_HEADER+b"V"+b"\xff\xff\xff\xff"


class SteamQueryError(RuntimeError):
    pass


def _cstring(data: bytes, offset: int) -> tuple[str,int]:
    end=data.find(b"\x00",offset)
    if end<0:
        raise SteamQueryError("truncated A2S string")
    return data[offset:end].decode("utf-8",errors="replace"),end+1


def _extract_printable_strings(data: bytes, minimum: int=3) -> list[str]:
    out=[];buf=bytearray()
    def flush():
        if len(buf)>=minimum:
            value=bytes(buf).decode("utf-8",errors="ignore").strip()
            if value and value not in out:out.append(value)
        buf.clear()
    for byte in data:
        if 32<=byte<=126:
            buf.append(byte)
        else:
            flush()
    flush()
    return out


def _parse_info(payload: bytes) -> dict[str,Any]:
    if len(payload)<6 or payload[:4]!=_HEADER or payload[4]!=0x49:
        raise SteamQueryError("invalid A2S_INFO response")
    offset=5
    protocol=payload[offset];offset+=1
    name,offset=_cstring(payload,offset)
    map_name,offset=_cstring(payload,offset)
    folder,offset=_cstring(payload,offset)
    game,offset=_cstring(payload,offset)
    if offset+9>len(payload):
        raise SteamQueryError("truncated A2S_INFO response")
    app_id=struct.unpack_from("<H",payload,offset)[0];offset+=2
    players=payload[offset];max_players=payload[offset+1];bots=payload[offset+2];offset+=3
    server_type=chr(payload[offset]);environment=chr(payload[offset+1]);visibility=payload[offset+2];vac=payload[offset+3];offset+=4
    version,offset=_cstring(payload,offset)
    return {
        "protocol":protocol,"name":name,"map":map_name,"folder":folder,"game":game,
        "app_id":app_id,"players":players,"max_players":max_players,"bots":bots,
        "server_type":server_type,"environment":environment,"password":bool(visibility),
        "vac":bool(vac),"version":version,
    }


def _parse_rules(payload: bytes) -> dict[str,Any]:
    if len(payload)<7 or payload[:4]!=_HEADER or payload[4]!=0x45:
        raise SteamQueryError("invalid A2S_RULES response")
    declared=struct.unpack_from("<H",payload,5)[0]
    offset=7;rules={}
    try:
        for _ in range(declared):
            key,offset=_cstring(payload,offset)
            value,offset=_cstring(payload,offset)
            if key:rules[key]=value
        return {"declared":declared,"rules":rules,"strings":[],"format":"key_value"}
    except SteamQueryError:
        strings=_extract_printable_strings(payload[7:])
        return {"declared":declared,"rules":{},"strings":strings,"format":"binary"}


def _recv_response(sock: socket.socket) -> bytes:
    first,_=sock.recvfrom(65535)
    if first.startswith(_HEADER):
        return first
    if not first.startswith(_SPLIT) or len(first)<12:
        raise SteamQueryError("invalid A2S packet")
    request_id=struct.unpack_from("<I",first,4)[0]
    if request_id & 0x80000000:
        raise SteamQueryError("compressed A2S split packets are not supported")
    total=first[8];number=first[9]
    if total<1 or number>=total:
        raise SteamQueryError("invalid A2S split packet")
    chunks={number:first[12:]}
    while len(chunks)<total:
        packet,_=sock.recvfrom(65535)
        if not packet.startswith(_SPLIT) or len(packet)<12:
            continue
        rid=struct.unpack_from("<I",packet,4)[0]
        if rid!=request_id:continue
        chunks[packet[9]]=packet[12:]
    joined=b"".join(chunks[index] for index in range(total))
    return joined if joined.startswith(_HEADER) else _HEADER+joined


def _challenge(sock: socket.socket, request: bytes) -> bytes:
    sock.send(request)
    response=_recv_response(sock)
    if len(response)>=9 and response[:4]==_HEADER and response[4]==0x41:
        challenge=response[5:9]
        sock.send(request+challenge)
        response=_recv_response(sock)
    return response


def query_steam_a2s(host: str, port: int, *, timeout: float=3.0) -> dict[str,Any]:
    host=str(host or "").strip()
    if not host:raise SteamQueryError("Steam Query host is unavailable")
    try:port=int(port)
    except (TypeError,ValueError) as exc:raise SteamQueryError("Steam Query port is invalid") from exc
    if not 1<=port<=65535:raise SteamQueryError("Steam Query port is invalid")
    addresses=socket.getaddrinfo(host,port,type=socket.SOCK_DGRAM)
    last_error=None
    for family,socktype,proto,_,sockaddr in addresses:
        sock=socket.socket(family,socktype,proto)
        try:
            sock.settimeout(max(.5,min(float(timeout),10.0)))
            sock.connect(sockaddr)
            info=_parse_info(_challenge(sock,_INFO_REQUEST))
            rules_result={"declared":0,"rules":{},"strings":[],"format":"unavailable"}
            try:
                rules_result=_parse_rules(_challenge(sock,_RULES_REQUEST))
            except (SteamQueryError,TimeoutError,socket.timeout,OSError):
                pass
            return {"online":True,"host":host,"port":port,"info":info,"rules":rules_result}
        except (SteamQueryError,TimeoutError,socket.timeout,OSError) as exc:
            last_error=exc
        finally:
            sock.close()
    raise SteamQueryError(str(last_error or "Steam Query did not respond"))


__all__=["SteamQueryError","query_steam_a2s"]
