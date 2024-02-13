"""Support for the Daikin HVAC."""
import logging

import voluptuous as vol

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    HVACMode,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_BOOST,
    PRESET_ECO,
    PRESET_NONE,
    ClimateEntityFeature,
    FAN_AUTO,
    SWING_OFF,
    SWING_BOTH,
    SWING_VERTICAL,
    SWING_HORIZONTAL,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_HOST,
    CONF_NAME,
    UnitOfTemperature,
)

import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN as DAIKIN_DOMAIN,
    DAIKIN_DEVICES,
    ATTR_LEAVINGWATER_TEMPERATURE,
    ATTR_OUTSIDE_TEMPERATURE,
    ATTR_ROOM_TEMPERATURE,
    ATTR_LEAVINGWATER_OFFSET,
    ATTR_STATE_OFF,
    ATTR_STATE_ON,
    ATTR_OPERATION_MODE,
    ATTR_TARGET_ROOM_TEMPERATURE,
    ATTR_TARGET_LEAVINGWATER_OFFSET,
    ATTR_TARGET_LEAVINGWATER_TEMPERATURE,
    FAN_QUIET,
)

import re

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {vol.Required(CONF_HOST): cv.string, vol.Optional(CONF_NAME): cv.string}
)

PRESET_MODES = {
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_AWAY,
    PRESET_BOOST
}

HA_HVAC_TO_DAIKIN = {
    HVACMode.FAN_ONLY: "fanOnly",
    HVACMode.DRY: "dry",
    HVACMode.COOL: "cooling",
    HVACMode.HEAT: "heating",
    HVACMode.HEAT_COOL: "auto",
    HVACMode.OFF: "off",
}

HA_ATTR_TO_DAIKIN = {
    ATTR_PRESET_MODE: "en_hol",
    ATTR_HVAC_MODE: "mode",
    ATTR_LEAVINGWATER_OFFSET: "c",
    ATTR_LEAVINGWATER_TEMPERATURE: "c",
    ATTR_OUTSIDE_TEMPERATURE: "otemp",
    ATTR_ROOM_TEMPERATURE: "stemp",
}

DAIKIN_HVAC_TO_HA = {
    "fanOnly": HVACMode.FAN_ONLY,
    "dry": HVACMode.DRY,
    "cooling": HVACMode.COOL,
    "heating": HVACMode.HEAT,
    "heatingDay": HVACMode.HEAT,
    "heatingNight": HVACMode.HEAT,
    "auto": HVACMode.HEAT_COOL,
    "off": HVACMode.OFF,
}

HA_PRESET_TO_DAIKIN = {
    PRESET_AWAY: "holidayMode",
    PRESET_NONE: "off",
    PRESET_BOOST: "powerfulMode",
    PRESET_COMFORT: "comfortMode",
    PRESET_ECO: "econoMode",
}

DAIKIN_FAN_TO_HA = {
    "auto": FAN_AUTO,
    "quiet": FAN_QUIET
}

HA_FAN_TO_DAIKIN = {
    DAIKIN_FAN_TO_HA["auto"]: "auto",
    DAIKIN_FAN_TO_HA["quiet"]: "quiet",
}

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Old way of setting up the Daikin HVAC platform.

    Can only be called when a user accidentally mentions the platform in their
    config. But even in that case it would have been ignored.
    """


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Daikin climate based on config_entry."""
    for dev_id, device in hass.data[DAIKIN_DOMAIN][DAIKIN_DEVICES].items():
        modes = []
        device_model = device.daikin_data["deviceModel"]
        supported_management_point_types = {'climateControl'}
        managementPoints = device.daikin_data.get("managementPoints", [])
        for management_point in managementPoints:
            management_point_type = management_point["managementPointType"]
            if  management_point_type in supported_management_point_types:
                # Check if we have a temperatureControl
                temperatureControl = management_point.get("temperatureControl")
                if temperatureControl is not None:
                    for operationmode in temperatureControl["value"]["operationModes"]:
                        #for modes in operationmode["setpoints"]:
                        for c in temperatureControl["value"]["operationModes"][operationmode]["setpoints"]:
                            _LOGGER.info("Found temperature mode %s", c)
                            modes.append(c)
        # Remove duplicates
        modes = list(dict.fromkeys(modes))
        _LOGGER.info("Climate: Device %s has modes %s", device_model, modes)
        for mode in modes:
            async_add_entities([DaikinClimate(device, mode)], update_before_add=True)

class DaikinClimate(ClimateEntity):
    """Representation of a Daikin HVAC."""
    _enable_turn_on_off_backwards_compatibility = False # Remove with HA 2025.1

    # Setpoint is the setpoint string under temperatureControl/value/operationsModes/mode/setpoints, for example roomTemperature/leavingWaterOffset
    def __init__(self, device, setpoint):
        """Initialize the climate device."""
        _LOGGER.info("Initializing Daiking Climate for controlling %s...", setpoint)
        self._device = device
        self._setpoint = setpoint

    async def _set(self, settings):
        raise NotImplementedError

    def climateControl(self):
        cc = None
        supported_management_point_types = {'climateControl'}
        if self._device.daikin_data["managementPoints"] is not None:
            for management_point in self._device.daikin_data["managementPoints"]:
                management_point_type = management_point["managementPointType"]
                if  management_point_type in supported_management_point_types:
                    cc = management_point
        return cc

    def operationMode(self):
        operationMode = None
        cc = self.climateControl()
        return cc.get("operationMode")

    def setpoint(self):
        setpoint = None
        cc = self.climateControl()
        # Check if we have a temperatureControl
        temperatureControl = cc.get("temperatureControl")
        if temperatureControl is not None:
            operationMode = cc.get("operationMode").get("value")
            # For not all operationModes there is a temperatureControl setpoint available
            oo = temperatureControl["value"]["operationModes"].get(operationMode)
            if oo is not None:
                setpoint = oo["setpoints"].get(self._setpoint)
            _LOGGER.info("Climate: %s operation mode %s has setpoint %s", self._setpoint, operationMode, setpoint)
        return setpoint

    # Return the dictionary fanControl for the current operationMode
    def fanControl(self):
        fancontrol = None
        supported_management_point_types = {'climateControl'}
        if self._device.daikin_data["managementPoints"] is not None:
            for management_point in self._device.daikin_data["managementPoints"]:
                management_point_type = management_point["managementPointType"]
                if  management_point_type in supported_management_point_types:
                    # Check if we have a temperatureControl
                    temperatureControl = management_point.get("fanControl")
                    _LOGGER.info("Climate: Device fanControl %s", temperatureControl)
                    if temperatureControl is not None:
                        operationMode = management_point.get("operationMode").get("value")
                        fancontrol = temperatureControl["value"]["operationModes"][operationMode].get(self._setpoint)
                        _LOGGER.info("Climate: %s operation mode %s has fanControl %s", self._setpoint, operationMode, setpoint)
        return setpoint

    def sensoryData(self):
        sensoryData = None
        supported_management_point_types = {'climateControl'}
        if self._device.daikin_data["managementPoints"] is not None:
            for management_point in self._device.daikin_data["managementPoints"]:
                management_point_type = management_point["managementPointType"]
                if  management_point_type in supported_management_point_types:
                    # Check if we have a sensoryData
                    sensoryData = management_point.get("sensoryData")
                    _LOGGER.info("Climate: Device sensoryData %s", sensoryData)
                    if sensoryData is not None:
                        sensoryData = sensoryData.get("value").get(self._setpoint)
                        _LOGGER.info("Climate: %s has sensoryData %s", self._setpoint, sensoryData)
        return sensoryData

    @property
    def embedded_id(self):
        cc = self.climateControl()
        return cc["embeddedId"]

    @property
    def available(self):
        """Return the availability of the underlying device."""
        return self._device.available

    @property
    def supported_features(self):
        supported_features = (ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON)
        setpointdict = self.setpoint()
        cc = self.climateControl()
        if setpointdict is not None and setpointdict["settable"] == True:
            supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if len(self.preset_modes) > 1:
            supported_features |= ClimateEntityFeature.PRESET_MODE
        fanControl = cc.get("fanControl")
        if fanControl is not None:
            operationmode = cc["operationMode"]["value"]
            if fanControl["value"]["operationModes"][operationmode].get("fanSpeed") is not None:
                supported_features |= ClimateEntityFeature.FAN_MODE
            if fanControl["value"]["operationModes"][operationmode].get("fanDirection") is not None:
                supported_features |= ClimateEntityFeature.SWING_MODE

        _LOGGER.info("Devices '%s' supports features %s", self._device.name, supported_features)

        return supported_features

    @property
    def name(self):
        device_name = self._device.name
        cc = self.climateControl()
        namepoint = cc.get("name")
        if namepoint is not None:
            device_name = namepoint["value"]
        myname = self._setpoint[0].upper() + self._setpoint[1:]
        readable = re.findall('[A-Z][^A-Z]*', myname)
        return f"{device_name} {' '.join(readable)}"

    @property
    def unique_id(self):
        """Return a unique ID."""
        devID = self._device.getId()
        return f"{devID}_{self._setpoint}"

    @property
    def temperature_unit(self):
        """Return the unit of measurement which this thermostat uses."""
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self):
        currentTemp = None
        sensoryData = self.sensoryData()
        setpointdict = self.setpoint()
        # Check if there is a sensoryData which is for the same setpoint, if so, return that
        if sensoryData is not None:
            currentTemp = sensoryData["value"]
        else:
            if setpointdict is not None:
                currentTemp = setpointdict["value"]
        _LOGGER.debug("Device '%s' current temperature '%s'", self._device.name, currentTemp)
        return currentTemp

    @property
    def max_temp(self):
        maxTemp = None
        setpointdict = self.setpoint()
        if setpointdict is not None:
            maxTemp = setpointdict["maxValue"]
        _LOGGER.debug("Device '%s' max temperature '%s'", self._device.name, maxTemp)
        return maxTemp

    @property
    def min_temp(self):
        minValue = None
        setpointdict = self.setpoint()
        if setpointdict is not None:
            minValue = setpointdict["minValue"]
        _LOGGER.debug("Device '%s' max temperature '%s'", self._device.name, minValue)
        return minValue

    @property
    def target_temperature(self):
        value = None
        setpointdict = self.setpoint()
        if setpointdict is not None:
            value = setpointdict["value"]
        _LOGGER.debug("Device '%s' target temperature '%s'", self._device.name, value)
        return value

    @property
    def target_temperature_step(self):
        stepValue = None
        setpointdict = self.setpoint()
        if setpointdict is not None:
            stepValue = setpointdict["stepValue"]
        _LOGGER.debug("Device '%s' step value '%s'", self._device.name, stepValue)
        return stepValue

    async def async_set_temperature(self, **kwargs):
        # """Set new target temperature."""
        operationmode = self.operationMode()
        omv = operationmode["value"]
        value = kwargs[ATTR_TEMPERATURE]
        res = await self._device.set_path(self._device.getId(), self.embedded_id, "temperatureControl", f"/operationModes/{omv}/setpoints/{self._setpoint}", value)
        # When updating the value to the daikin cloud worked update our local cached version
        if res:
            setpointdict = self.setpoint()
            if setpointdict is not None:
                setpointdict["value"] = value

    @property
    def hvac_mode(self):
        """Return current HVAC mode."""
        mode = HVACMode.OFF
        operationmode = self.operationMode()
        cc = self.climateControl()
        if cc["onOffMode"]["value"] != "off":
            mode = operationmode["value"]
        return DAIKIN_HVAC_TO_HA.get(mode, HVACMode.HEAT_COOL)

    @property
    def hvac_modes(self):
        """Return the list of available HVAC modes."""
        modes = [HVACMode.OFF]
        operationmode = self.operationMode()
        if operationmode is not None:
            for mode in operationmode["values"]:
                ha_mode = DAIKIN_HVAC_TO_HA[mode]
                if ha_mode not in modes:
                    modes.append(ha_mode)
        return modes

    async def async_set_hvac_mode(self, hvac_mode):
        """Set HVAC mode."""
        result = True

        # First determine the new settings for onOffMode/operationMode, we need these to set them to Daikin
        # and update our local cached version when succeeded
        onOffMode = None
        operationMode = None
        if hvac_mode == HVACMode.OFF:
            onOffMode = "off"
        else:
            if self.hvac_mode == HVACMode.OFF:
                onOffMode = "on"
            operationMode = HA_HVAC_TO_DAIKIN[hvac_mode]

        cc = self.climateControl()

        # Only set the on/off to Daikin when we need to change it
        if onOffMode is not None:
            result &= await self._device.set_path(self._device.getId(), self.embedded_id, "onOffMode", "", onOffMode)
            if result is False:
                _LOGGER.warning("Device '%s' problem setting onOffMode to %s", self._device.name, onOffMode)
            else:
                cc["onOffMode"]["value"] = onOffMode

        if operationMode is not None:
            result &= await self._device.set_path(self._device.getId(), self.embedded_id, "operationMode", "", operationMode)
            if result is False:
                _LOGGER.warning("Device '%s' problem setting operationMode to %s", self._device.name, operationMode)
            else:
                cc["operationMode"]["value"] = operationMode

        return result

    @property
    def fan_mode(self):
        fan_mode = None
        cc = self.climateControl()
        # Check if we have a fanControl
        fanControl = cc.get("fanControl")
        if fanControl is not None:
            operationmode = cc["operationMode"]["value"]
            fanspeed = fanControl["value"]["operationModes"][operationmode]["fanSpeed"]
            mode = fanspeed["currentMode"]["value"]
            if mode in DAIKIN_FAN_TO_HA:
                fan_mode = DAIKIN_FAN_TO_HA[mode]
            else:
                fsm = fanspeed.get("modes")
                if fsm is not None:
                    _LOGGER.info("FSM %s", fsm)
                    fixedModes = fsm[mode]
                    fan_mode = str(fixedModes["value"])

        return fan_mode

    @property
    def fan_modes(self):
        fan_modes = []
        fanspeed = None
        cc = self.climateControl()
        # Check if we have a fanControl
        fanControl = cc.get("fanControl")
        if fanControl is not None:
            operationmode = cc["operationMode"]["value"]
            fanspeed = fanControl["value"]["operationModes"][operationmode]["fanSpeed"]
            _LOGGER.info("Found fanspeed %s", fanspeed)
            for c in fanspeed["currentMode"]["values"]:
                _LOGGER.info("Found fan mode %s", c)
                if c in DAIKIN_FAN_TO_HA:
                    fan_modes.append(DAIKIN_FAN_TO_HA[c])
                else:
                    fsm = fanspeed.get("modes")
                    if fsm is not None:
                        _LOGGER.info("Found fixed %s", fsm)
                        fixedModes = fsm[c]
                        minVal = int(fixedModes["minValue"])
                        maxVal = int(fixedModes["maxValue"])
                        stepValue = int(fixedModes["stepValue"])
                        for val in range(minVal, maxVal + 1, stepValue):
                            fan_modes.append(str(val))

        return fan_modes

    async def async_set_fan_mode(self, fan_mode):
        """Set the preset mode status."""
        cc = self.climateControl()
        fanControl = cc.get("fanControl")
        operationmode = cc["operationMode"]["value"]
        if fan_mode in HA_FAN_TO_DAIKIN.keys():
            res = await self._device.set_path(self._device.getId(), self.embedded_id, "fanControl", f"/operationModes/{operationmode}/fanSpeed/currentMode", fan_mode)
            if res is False:
                _LOGGER.warning("Device '%s' problem setting fan_mode to %s", self._device.name, fan_mode)
            else:
                fanControl["value"]["operationModes"][operationmode]["fanSpeed"]["currentMode"]["value"] = fan_mode

        else:
            if fan_mode.isnumeric():
                mode = int(fan_mode)
                res = await self._device.set_path(self._device.getId(), self.embedded_id, "fanControl", f"/operationModes/{operationmode}/fanSpeed/currentMode", "fixed")
                if res is False:
                    _LOGGER.warning("Device '%s' problem setting fan_mode to fixed", self._device.name)
                else:
                    fanControl["value"]["operationModes"][operationmode]["fanSpeed"]["currentMode"]["fixed"] = fan_mode
                res &= await self._device.set_path(self._device.getId(), self.embedded_id, "fanControl", f"/operationModes/{operationmode}/fanSpeed/modes/fixed", mode)
                if res is False:
                    _LOGGER.warning("Device '%s' problem setting fan_mode fixed to %s", self._device.name, mode)
                else:
                    fanControl["value"]["operationModes"][operationmode]["fanSpeed"]["modes"]["fixed"]["value"] = int(fan_mode)

        return res

    @property
    def swing_mode(self):
        swingMode = SWING_OFF
        cc = self.climateControl()
        fanControl = cc.get("fanControl")
        h = SWING_OFF
        v = SWING_OFF
        if fanControl is not None:
            operationmode = cc["operationMode"]["value"]
            fanDirection = fanControl["value"]["operationModes"][operationmode].get("fanDirection")
            if fanDirection is not None:
                horizontal = fanDirection.get("horizontal")
                vertical = fanDirection.get("vertical")
                if horizontal is not None:
                    h = horizontal["currentMode"]["value"]
                if vertical is not None:
                    v = vertical["currentMode"]["value"]
        if h == "swing":
            swingMode = SWING_HORIZONTAL
        if v == "swing":
            swingMode = SWING_VERTICAL
        if v == "swing" and h == "swing":
            swingMode = SWING_BOTH
        if v == "floorHeatingAirflow":
            swingMode = "floorHeatingAirflow"
        if v == "windNice":
            if h == "swing":
                swingMode = "Comfort Airflow and Horizontal"
            else:
                swingMode = "Comfort Airflow"

        _LOGGER.info("Device '%s' has swing mode '%s', determined from h:%s v:%s", self._device.name, swingMode, h, v)

        return swingMode

    @property
    def swing_modes(self):
        swingModes = [SWING_OFF]
        cc = self.climateControl()
        fanControl = cc.get("fanControl")
        if fanControl is not None:
            operationmode = cc["operationMode"]["value"]
            fanDirection = fanControl["value"]["operationModes"][operationmode].get("fanDirection")
            if fanDirection is not None:
                horizontal = fanDirection.get("horizontal")
                vertical = fanDirection.get("vertical")
                if horizontal is not None:
                    for mode in horizontal["currentMode"]["values"]:
                        if mode == "swing":
                            swingModes.append(SWING_HORIZONTAL)
                        if mode == "floorHeatingAirflow":
                            swingModes.append(mode)
                if vertical is not None:
                    for mode in vertical["currentMode"]["values"]:
                        if mode == "swing":
                            swingModes.append(SWING_VERTICAL)
                            if horizontal is not None:
                                swingModes.append(SWING_BOTH)
                        if mode == "floorHeatingAirflow":
                            swingModes.append(mode)
                        if mode == "windNice":
                            swingModes.append("Comfort Airflow")
                            if horizontal is not None:
                                swingModes.append("Comfort Airflow and Horizontal")
        _LOGGER.info("Device '%s' support swing modes %s", self._device.name, swingModes)
        return swingModes

    async def async_set_swing_mode(self, swing_mode):
        res = True
        cc = self.climateControl()
        fanControl = cc.get("fanControl")
        operationmode = cc["operationMode"]["value"]
        if fanControl is not None:
            operationmode = cc["operationMode"]["value"]
            fanDirection = fanControl["value"]["operationModes"][operationmode].get("fanDirection")
            if fanDirection is not None:
                horizontal = fanDirection.get("horizontal")
                vertical = fanDirection.get("vertical")
                if horizontal is not None:
                    new_hMode = "stop"
                    if swing_mode in (SWING_HORIZONTAL, SWING_BOTH, "Comfort Airflow and Horizontal"):
                        new_hMode = "swing"
                    res &= await self._device.set_path(self._device.getId(), self.embedded_id, "fanControl", f"/operationModes/{operationmode}/fanDirection/horizontal/currentMode", new_hMode)
                    if res is False:
                        _LOGGER.warning("Device '%s' problem setting horizontal swing mode to %s", self._device.name, new_hMode)
                    else:
                        fanControl["value"]["operationModes"][operationmode]["fanDirection"]["horizontal"]["currentMode"]["value"] = new_hMode
                if vertical is not None:
                    new_vMode = "stop"
                    if swing_mode in (SWING_VERTICAL, SWING_BOTH):
                        new_vMode = "swing"
                    if swing_mode in ("floorHeatingAirflow"):
                        new_vMode = "floorHeatingAirflow"
                    if swing_mode in ("Comfort Airflow", "Comfort Airflow and Horizontal"):
                        new_vMode = "windNice"
                    res &= await self._device.set_path(self._device.getId(), self.embedded_id, "fanControl", f"/operationModes/{operationmode}/fanDirection/vertical/currentMode", new_vMode)
                    if res is False:
                        _LOGGER.warning("Device '%s' problem setting vertical swing mode to %s", self._device.name, new_vMode)
                    else:
                        fanControl["value"]["operationModes"][operationmode]["fanDirection"]["vertical"]["currentMode"]["value"] = new_vMode

        return res

    @property
    def preset_mode(self):
        cc = self.climateControl()
        current_preset_mode = PRESET_NONE
        for mode in self.preset_modes:
            daikin_mode = HA_PRESET_TO_DAIKIN[mode]
            preset = cc.get(daikin_mode)
            if preset is not None:
                preset_value = preset.get("value")
                if preset_value is not None and preset_value == "on":
                    current_preset_mode = mode
        return current_preset_mode

    async def async_set_preset_mode(self, preset_mode):
        result = True
        new_daikin_mode = HA_PRESET_TO_DAIKIN[preset_mode]
        cc = self.climateControl()
        preset = cc.get(new_daikin_mode)

        if self.preset_mode != PRESET_NONE:
            current_mode = HA_PRESET_TO_DAIKIN[self.preset_mode]
            result &= await self._device.set_path(self._device.getId(), self.embedded_id, current_mode, "", "off")
            if result is False:
                _LOGGER.warning("Device '%s' problem setting %s to off", self._device.name, current_mode)
            else:
                cc[current_mode]["value"] = "off"

        if preset_mode != PRESET_NONE:
            if self.hvac_mode == HVACMode.OFF and preset_mode == PRESET_BOOST:
                result &= await self.async_turn_on()

            result &= await self._device.set_path(self._device.getId(), self.embedded_id, new_daikin_mode, "", "on")
            if result is False:
                _LOGGER.warning("Device '%s' problem setting %s to on", self._device.name, new_daikin_mode)
            else:
                cc[new_daikin_mode]["value"] = "on"

        return result

    @property
    def preset_modes(self):
        supported_preset_modes = [PRESET_NONE]
        cc = self.climateControl()
        # self._current_preset_mode = PRESET_NONE
        for mode in PRESET_MODES:
            daikin_mode = HA_PRESET_TO_DAIKIN[mode]
            preset = cc.get(daikin_mode)
            if preset is not None and preset.get("value") is not None:
                supported_preset_modes.append(mode)

        _LOGGER.info("Devices '%s' supports pre preset_modes %s", self._device.name, format(supported_preset_modes))

        return supported_preset_modes

    async def async_update(self):
        """Retrieve latest state."""
        _LOGGER.debug("Device '%s' climate async_update", self._device.name)
        await self._device.api.async_update()

    async def async_turn_on(self):
        """Turn device CLIMATE on."""
        cc = self.climateControl()
        result = await self._device.set_path(self._device.getId(), self.embedded_id, "onOffMode", "", "on")
        if result is False:
          _LOGGER.warning("Device '%s' problem setting onOffMode to on", self._device.name)
        else:
           cc["onOffMode"]["value"] = "on"
        return result

    async def async_turn_off(self):
        cc = self.climateControl()
        result = await self._device.set_path(self._device.getId(), self.embedded_id, "onOffMode", "", "off")
        if result is False:
          _LOGGER.warning("Device '%s' problem setting onOffMode to off", self._device.name)
        else:
           cc["onOffMode"]["value"] = "off"
        return result

    @property
    def device_info(self):
        """Return a device description for device registry."""
        return self._device.device_info()
