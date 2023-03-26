from __future__ import annotations
from collections.abc import Callable

import re
import time
from dataclasses import dataclass

import aiohttp
import xmltodict  # type: ignore

import asyncio
from discovery30303 import Device30303, AIODiscovery30303, MODEL_550, MODEL_450

__author__ = """J. Nick Koston"""
__email__ = "nick@koston.org"
__version__ = "0.3.2+jm1"

DEFAULT_REQUEST_TIMEOUT = 10
STATUS_ENDPOINT = "/status.xml"
SET_ENDPOINT = "/leds.cgi"

TEMP_REGEX_F = re.compile("([0-9]+)XF")
TEMP_REGEX_C = re.compile("([0-9]+)XC")


STEAM_ON_LED = 6
STEAM_OFF_LED = 7

NEVER_TIME = -1200


@dataclass
class SteamistStatus:
    """Status data from a Steamist controller"""

    temp: int = 0
    temp_units: str = ""
    minutes_remain: int = 0
    seconds_remain: int = 0
    active: bool = False

    @staticmethod
    def create_from_device_30303(steamist: Device30303) -> SteamistStatus:
        """Factory method returning a status from a Device30303 discovery data"""
        status = SteamistStatus()
        status.temp = steamist.additional_data["temperature"]
        status.temp_units = steamist.additional_data["temp_unit"]
        status.minutes_remain = steamist.additional_data["minutesleft"]
        status.seconds_remain = steamist.additional_data["secondsleft"]
        status.active = steamist.additional_data["profile"] != 0

        return status


class Steamist:
    """Async steamist api."""

    def __init__(
        self,
        host: str,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        """Create steamist async api object."""
        self._host = host
        self._timeout = timeout
        self._transition_complete_time = NEVER_TIME
        self._transiton_state: bool = False
        self._auth_invalid = 0

    def _async_set_transition(self, state: bool) -> None:
        self._transiton_state = state
        self._transition_complete_time = time.monotonic() + 10

    async def async_turn_on_steam(self) -> None:
        """Call to turn on the steam."""
        self._async_set_transition(True)

    async def async_turn_off_steam(self) -> None:
        """Call to turn off the steam."""
        self._async_set_transition(False)

    async def async_get_status(self) -> SteamistStatus:
        """Get status from device"""
        raise NotImplementedError("Sub class should implement")

    @staticmethod
    def model() -> str:
        """Return the model string returned by device"""
        raise NotImplementedError("Must be overriden by subclass")

    @staticmethod
    def create_steamist_from(
        host: str, model: str, websession: Callable[[], aiohttp.ClientSession]
    ) -> Steamist:
        """Based on model, instantiate the proper implementation"""
        if model == SteamistModel550.model():
            return SteamistModel550(host)
        else:
            return SteamistModel450(host, websession())


class SteamistModel550(Steamist):
    """Steamist Controller Model 550"""

    async def async_get_status(self) -> SteamistStatus:
        """Call api to get status."""
        scanner = AIODiscovery30303()
        task = asyncio.ensure_future(scanner.async_scan(timeout=5, address=self._host))
        await task
        if len(scanner.found_devices) > 0:
            return SteamistStatus.create_from_device_30303(scanner.found_devices[0])

    @staticmethod
    def model() -> str:
        """Return the model string returned by device"""
        return MODEL_550


class SteamistModel450(Steamist):
    """Async steamist api."""

    def __init__(
        self,
        host: str,
        websession: aiohttp.ClientSession,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        """Create steamist async api object."""
        Steamist.__init__(self, host, timeout)
        self._websession = websession

    async def _get(self, endpoint: str, params=None) -> str:
        """Make a get request."""
        response = await self._websession.request(
            "GET",
            f"http://{self._host}{endpoint}",
            timeout=self._timeout,
            params=params,
        )
        return await response.text()

    async def async_get_status(self) -> SteamistStatus:
        """Call api to get status."""
        data: dict = xmltodict.parse(await self._get(STATUS_ENDPOINT))
        response = data["response"]
        groups_f = TEMP_REGEX_F.match(response["temp0"])
        groups_c = TEMP_REGEX_C.match(response["temp0"])
        units = "F"
        temp = None
        if groups_f:
            temp = int(groups_f[1])
        elif groups_c:
            temp = int(groups_c[1])
            units = "C"
        minutes_remain = int(response["time0"])
        if self._transition_complete_time > time.monotonic():
            active = self._transiton_state
        else:
            active = minutes_remain > 0
        return SteamistStatus(
            # TODO: seconds_remain was added for the 550.  Doesn't the 450 have this?
            temp=temp,
            temp_units=units,
            minutes_remain=minutes_remain,
            active=active,
            seconds_remain=0,
        )

    async def async_turn_on_steam(self) -> None:
        """Call to turn on the steam."""
        await self.async_set_led(STEAM_ON_LED)
        self._async_set_transition(True)

    async def async_turn_off_steam(self) -> None:
        """Call to turn off the steam."""
        await self.async_set_led(STEAM_OFF_LED)
        self._async_set_transition(False)

    async def async_set_led(self, id: int) -> None:
        """Call to set a led value."""
        await self._get(SET_ENDPOINT, {"led": id})

    @staticmethod
    def model() -> str:
        """Return the model string returned by device"""
        return MODEL_450
