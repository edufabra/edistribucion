import logging
from homeassistant.const import POWER_KILO_WATT
from homeassistant.helpers.entity import Entity
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.event import async_track_point_in_time
from .api.EdistribucionAPI import Edistribucion
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=10)
FRIENDLY_NAME = 'EDS Consumo eléctrico'

SERVICE_RECONNECT_ICP = "reconnect_icp"

async def async_setup_platform(hass, config, add_entities, discovery_info=None):

    # Define entities
    entities = []
    eds = EDSSensor(config['username'],config['password'])
    entities.append(eds)

    # Register services
    platform = entity_platform.current_platform.get()
    platform.async_register_entity_service(
            SERVICE_RECONNECT_ICP,
            {},
            EDSSensor.reconnect_ICP.__name__,
        )

    # Register listeners
    def handle_next_day (self):
        for entity in entities:
            entity.handle_next_day ()

    # Set schedulers
    def schedule_next_day (self):
        today = datetime.today()
        tomorrow_begins = today.replace(hour=0, minute=0, second=0) + timedelta(days=1)
        async_track_point_in_time(
            hass, handle_next_day, datetime.as_utc(tomorrow_begins)
        )

    """Set up the sensor platform."""
    add_entities(entities)

    # Start schedulers
    schedule_next_day

class EDSSensor(Entity):
    """Representation of a Sensor."""

    def __init__(self,usr,pw):
        """Initialize the sensor."""
        self._state = None
        self._attributes = {}
        self._usr=usr
        self._pw=pw

        self._is_first_boot = True
        self._do_run_daily_tasks = False

        self._total_consumption = 0
        self._total_consumption_yesterday = 0

    @property
    def name(self):
        """Return the name of the sensor."""
        return FRIENDLY_NAME

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def icon(self):
        """Return the icon to be used for this entity."""
        return "mdi:flash" 

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return POWER_KILO_WATT

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._attributes

    def handle_next_day (self):
        self._do_run_daily_tasks = True

    def reconnect_ICP (self):
        ### Untested... impossible under the current setup
        _LOGGER.debug("ICP reconnect service called")
        # Login into the edistribucion platform. 
        edis = Edistribucion(self._usr,self._pw,True)
        edis.login()
        # Get CUPS list, at the moment we just explore the first element [0] in the table (valid if you only have a single contract)
        r = edis.get_list_cups()
        cups = r[0]['CUPS_Id']
        # Get response
        response = edis.reconnect_ICP(cups)
        _LOGGER.debug(response)

    def update(self):
        """Fetch new state data for the sensor."""
        attributes = {}

        # Login into the edistribucion platform. 
        edis = Edistribucion(self._usr,self._pw,True)
        edis.login()
        # Get CUPS list, at the moment we just explore the first element [0] in the table (valid if you only have a single contract)
        r = edis.get_list_cups()
        cups = r[0]['CUPS_Id']
        cont = r[0]['Id']

        attributes['CUPS'] = r[0]['CUPS'] # this is the name
        #attributes['Cont'] = cont # not really needed

        # First retrieve historical data if first boot or starting a new day (this is fast)
        if self._is_first_boot or self._do_run_daily_tasks:
            yesterday = (datetime.today()-timedelta(days=1)).strftime("%Y-%m-%d")
            sevendaysago = (datetime.today()-timedelta(days=8)).strftime("%Y-%m-%d")
            onemonthago = (datetime.today()-timedelta(days=30)).strftime("%Y-%m-%d")

            yesterday_curve=edis.get_day_curve(cont,yesterday)
            attributes['Consumo total (ayer)'] = str(yesterday_curve['data']['totalValue']) + ' kWh'
            lastweek_curve=edis.get_week_curve(cont,sevendaysago)
            attributes['Consumo total (7 días)'] = str(lastweek_curve['data']['totalValue']) + ' kWh'
            lastmonth_curve=edis.get_month_curve(cont,onemonthago)
            attributes['Consumo total (30 días)'] = str(lastmonth_curve['data']['totalValue']) + ' kWh'

            thismonth = datetime.today().strftime("%m/%Y")
            ayearplusamonthago = (datetime.today()-timedelta(days=395)).strftime("%m/%Y")
            maximeter_histogram = edis.get_year_maximeter (cups, ayearplusamonthago, thismonth)
            attributes['Máxima potencia registrada'] = maximeter_histogram['data']['maxValue']

        # Then retrieve instant data (this is slow)

        meter = edis.get_meter(cups)
        _LOGGER.debug(meter)
        _LOGGER.debug(meter['data']['potenciaActual'])
        
        attributes['Estado ICP'] = meter['data']['estadoICP']
        self._total_consumption = float(meter['data']['totalizador'])
        attributes['Consumo total'] = str(meter['data']['totalizador']) + ' kWh'
        attributes['Carga actual'] = meter['data']['percent']
        attributes['Potencia contratada'] = str(meter['data']['potenciaContratada']) + ' kW'
        
        # if new day, store consumption
        if self._do_run_daily_tasks or self._is_first_boot:
            self._total_consumption_yesterday = float(self._total_consumption)

        attributes['Consumo total (hoy)'] = str(self._total_consumption - self._total_consumption_yesterday) + ' kWh'

        self._state = meter['data']['potenciaActual']
        self._attributes = attributes

        # set flags down
        self._do_run_daily_tasks = False
        self._is_first_boot = False
        