#!/usr/bin/env python

"""
@file ion/services/sa/test/test_instrument_management.py
@test ion.services.sa.data_acquisition Example unit tests for sample code.
@author Michael Meisinger
"""

import ion.util.ionlog
log = ion.util.ionlog.getLogger(__name__)
from twisted.internet import defer


#from ion.agents.instrumentagents.instrument_agent import InstrumentAgentClient
#from ion.agents.instrumentagents.simulators.sim_SBE49 import Simulator
#from ion.services.coi.agent_registry import AgentRegistryClient
from ion.services.sa.instrument_management import InstrumentManagementClient
from ion.agents.instrumentagents.instrument_constants import DriverCommand
from ion.test.iontest import IonTestCase
from ion.services.coi.resource_registry.resource_registry import ResourceRegistryClient, ResourceRegistryError
from ion.services.coi.resource_registry.resource_client import ResourceClient, ResourceInstance, RESOURCE_TYPE
from ion.services.dm.distribution.events import InstrumentSampleDataEventPublisher
from ion.services.coi.datastore_bootstrap.ion_preload_config import ION_RESOURCE_TYPES, ION_IDENTITIES, ID_CFG, PRELOAD_CFG, ION_DATASETS_CFG, ION_DATASETS, NAME_CFG, DEFAULT_RESOURCE_TYPE_ID

import ion.util.procutils as pu


class InstrumentManagementTest(IonTestCase):
    """
    Testing instrument management service
    """

    @defer.inlineCallbacks
    def setUp(self):
        yield self._start_container()

        services = [
            {
                'name':'instmgmt',
                'module':'ion.services.sa.instrument_management',
                'class':'InstrumentManagementService'
            },
            {
                'name':'ds1',
                'module':'ion.services.coi.datastore',
                'class':'DataStoreService',
                'spawnargs':{PRELOAD_CFG:{ION_DATASETS_CFG:True}}

            },
            {
                'name':'association_service',
                'module':'ion.services.dm.inventory.association_service',
                'class':'AssociationService'
            },
            {
                'name':'resource_registry1',
                'module':'ion.services.coi.resource_registry.resource_registry',
                'class':'ResourceRegistryService',
                'spawnargs':{'datastore_service':'datastore'}
            },
        ]

        sup = yield self._spawn_processes(services)
        self.sup = sup

        self.rrc = ResourceRegistryClient(proc=sup)
        self.rc = ResourceClient(proc=sup)
        self.imc = InstrumentManagementClient(proc=sup)
        self.user_id = 0;

    @defer.inlineCallbacks
    def tearDown(self):
        yield self._shutdown_processes()
        yield self._stop_container()


    @defer.inlineCallbacks
    def test_create_instrument(self):
        """
        Accepts an dictionary containing updates to the instrument registry.
        Updates are made to the registries.
        """

        log.info("IMSSRVC test_create_instrument Now testing: Create instrument from UI")
        userUpdate = {'manufacturer' : "SeaBird Electronics",
                 'model' : "unknown model",
                 'serial_num' : "1234",
                 'fw_version' : "1"}

        result = yield self.imc.create_new_instrument(userUpdate)
        log.info("IMSSRVC test_create_instrument  instrument id: %s ", result['instrument_id'] )


        """
        #now create a instrument agent and associate
        instAgentParams = {'instrumentID' : "SeaBird Electronics",
            'instrumentResourceID' : result['instrument_id'],
            'model' : "SBE49"}
        result = yield self.imc.start_instrument_agent("SeaBird Electronics", result['instrument_id'], "SBE49")
        #result = yield self.imc.start_instrument_agent(instAgentParams)
        #start_instrument_agent(self, instrumentID, instrumentResourceID, model):
        log.info("IMSSRVC test_create_instrument  instrument agent id: %s ", result['instrument_agent_id'] )
        """


        log.info("IMSSRVC test_create_instrument Finished testing: Create instrument from UI")


    #@defer.inlineCallbacks
    def Xtest_direct_access(self):
        """
        Switches direct_access mode to ON in the instrument registry.
        """


class TestInstMgmtRT(IonTestCase):

    #Testing instrument management service in end-to-end roundtrip mode

    @defer.inlineCallbacks
    def setUp(self):
        yield self._start_container()

        services = [
            {
                'name':'instmgmt',
                'module':'ion.services.sa.instrument_management',
                'class':'InstrumentManagementService'
            },
            {
                'name':'ds1',
                'module':'ion.services.coi.datastore',
                'class':'DataStoreService',
                'spawnargs':{PRELOAD_CFG:{ION_DATASETS_CFG:True}}

            },
            {
                'name':'association_service',
                'module':'ion.services.dm.inventory.association_service',
                'class':'AssociationService'
            },
            {
                'name':'resource_registry1',
                'module':'ion.services.coi.resource_registry.resource_registry',
                'class':'ResourceRegistryService',
                'spawnargs':{'datastore_service':'datastore'}
            },
        ]


        sup = yield self._spawn_processes(services)
        self.sup = sup

        self.rrc = ResourceRegistryClient(proc=sup)
        self.rc = ResourceClient(proc=sup)
        self.imc = InstrumentManagementClient(proc=sup)



    @defer.inlineCallbacks
    def tearDown(self):
        yield self._stop_container()

    @defer.inlineCallbacks
    def test_get_status(self):
        #Get status back from instrument agent associated with instrument id
        #res = yield self.imc.get_instrument_state(self.inst_id)
        #self.assertNotEqual(res, None)
        #log.info("Instrument status: " +str(res))
        log.info("IMSSRVC test_get_status")
        userUpdate = {'manufacturer' : "SeaBird Electronics",
                 'model' : "SBE37",
                 'serial_num' : "1234",
                 'fw_version' : "1"}

        result = yield self.imc.create_new_instrument(userUpdate)
        log.info("IMSSRVC test_execute_command  instrument id: %s ", result['instrument_id'] )

        result = yield self.imc.start_instrument_agent("SeaBird Electronics", result['instrument_id'], "SBE37")
        log.info("IMSSRVC test_execute_command  instrument agent id: %s ", result['instrument_agent_id'] )

        result = yield self.imc.get_instrument_state(result['instrument_agent_id'])
        log.info("IMSSRVC test_execute_command  instrument state: %s ", result )

        log.info("IMSSRVC test_get_status completed")

    @defer.inlineCallbacks
    def test_execute_command(self):
        #Execute command through instrument agent associated with instrument id

        #res = yield self.imc.execute_command(self.inst_id, 'start', [1])
        #log.info("Command result 1" +str(res))

        log.info("IMSSRVC test_execute_command")
        userUpdate = {'manufacturer' : "SeaBird Electronics",
                 'model' : "SBE37",
                 'serial_num' : "1234",
                 'fw_version' : "1"}

        result = yield self.imc.create_new_instrument(userUpdate)
        log.info("IMSSRVC test_execute_command  instrument id: %s ", result['instrument_id'] )

        result = yield self.imc.start_instrument_agent("SeaBird Electronics", result['instrument_id'], "SBE37")
        log.info("IMSSRVC test_execute_command  instrument agent id: %s ", result['instrument_agent_id'] )

        cmd = [DriverCommand.ACQUIRE_SAMPLE]
        result = yield self.imc.execute_command(result['instrument_agent_id'], cmd)
        log.info("IMSSRVC test_execute_command  instrument state: %s ", result )

        log.info("IMSSRVC test_get_status completed")

        log.info("IMSSRVC test_execute_command completed")

    @defer.inlineCallbacks
    def test_start_agent(self):
        #Start the agent with all

        log.info("IMSSRVC test_create_instrument Now testing: Create instrument from UI")
        userUpdate = {'manufacturer' : "SeaBird Electronics",
                 'model' : "SBE37",
                 'serial_num' : "1234",
                 'fw_version' : "1"}

        result = yield self.imc.create_new_instrument(userUpdate)
        log.info("IMSSRVC test_create_instrument  instrument id: %s ", result['instrument_id'] )

        result = yield self.imc.start_instrument_agent("SeaBird Electronics", result['instrument_id'], "SBE37")
        log.info("IMSSRVC test_create_instrument  instrument agent id: %s ", result['instrument_agent_id'] )

        dataDict = "conductivity:0.3444;pressure:0.3732;temperature:28.0;sound velocity:3838.3;salinity:0.993;time:(15,33,30);date:(2011,5,5)"

        pubDataEvent = InstrumentSampleDataEventPublisher(process=self.sup, origin=result['instrument_agent_id']) # all publishers/subscribers need a process associated
        yield pubDataEvent.initialize()
        yield pubDataEvent.activate()

        log.info("IMSSRVC test_create_instrument  publish event")

        yield pubDataEvent.create_and_publish_event(origin=result['instrument_agent_id'],
                                                    conductivity=0.3444,
                                                    pressure=0.3732,
                                                    temperature=28.0,
                                                    sound_velocity=3838.3,
                                                    salinity=0.993,
                                                    time="(15,33,30)",
                                                    date="(2011,5,5)")
                                         #  datasource_id="dataresrc123",
                                         #  data_block=dataDict)

        log.info("IMSSRVC test_create_instrument  publish event completed")

        yield pu.asleep(3.0)