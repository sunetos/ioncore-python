#!/usr/bin/env python

"""
@file ion/integration/ais/manageDataResource/manageDataResource.py
@author Ian Katz
@brief The worker class that implements the data resource functions for the AIS  (workflow #105, #106)
"""

import ion.util.ionlog
log = ion.util.ionlog.getLogger(__name__)
from twisted.internet import defer

from ion.core.exception import ReceivedApplicationError
#from ion.core.messaging.message_client import MessageClient
#from ion.services.coi.resource_registry.resource_client import ResourceClient

from ion.core.object import object_utils

from ion.services.dm.inventory.dataset_controller import DatasetControllerClient
from ion.services.dm.ingestion.ingestion import IngestionClient
from ion.services.dm.scheduler.scheduler_service import SchedulerServiceClient, \
                                                        SCHEDULE_TYPE_PERFORM_INGESTION_UPDATE

from ion.services.dm.distribution.events import ScheduleEventPublisher

from ion.util.iontime import IonTime
import time

import re

from ion.services.coi.resource_registry.association_client import AssociationClient
from ion.services.coi.datastore_bootstrap.ion_preload_config import HAS_A_ID, \
                                                                    DATASET_RESOURCE_TYPE_ID, \
                                                                    DATASOURCE_RESOURCE_TYPE_ID, \
                                                                    DATARESOURCE_SCHEDULE_TYPE_ID



from ion.integration.ais.ais_object_identifiers import AIS_RESPONSE_MSG_TYPE, \
                                                       AIS_REQUEST_MSG_TYPE, \
                                                       AIS_RESPONSE_ERROR_TYPE, \
                                                       CREATE_DATA_RESOURCE_REQ_TYPE, \
                                                       CREATE_DATA_RESOURCE_RSP_TYPE, \
                                                       UPDATE_DATA_RESOURCE_REQ_TYPE, \
                                                       UPDATE_DATA_RESOURCE_RSP_TYPE, \
                                                       DELETE_DATA_RESOURCE_REQ_TYPE, \
                                                       DELETE_DATA_RESOURCE_RSP_TYPE, \
                                                       DATA_RESOURCE_SCHEDULED_TASK_TYPE

INGESTER_CREATETOPICS_REQ_MSG  = object_utils.create_type_identifier(object_id=2003, version=1)
RESOURCE_CFG_REQUEST_TYPE      = object_utils.create_type_identifier(object_id=10, version=1)
RESOURCE_CFG_RESPONSE_TYPE     = object_utils.create_type_identifier(object_id=12, version=1)
SA_DATASOURCE_RESOURCE_MSG     = object_utils.create_type_identifier(object_id=4503, version=1)
SCHEDULER_ADD_REQ_TYPE         = object_utils.create_type_identifier(object_id=2601, version=1)
SCHEDULER_ADD_RSP_TYPE         = object_utils.create_type_identifier(object_id=2602, version=1)
SCHEDULER_DEL_REQ_TYPE         = object_utils.create_type_identifier(object_id=2603, version=1)
SCHEDULER_DEL_RSP_TYPE         = object_utils.create_type_identifier(object_id=2604, version=1)
SCHEDULER_PERFORM_INGEST       = object_utils.create_type_identifier(object_id=2607, version=1)


DEFAULT_MAX_INGEST_MILLIS = 30000


class ManageDataResource(object):

    def __init__(self, ais):
        log.debug('ManageDataResource.__init__()')
        self._proc = ais
        self.mc    = ais.mc
        self.rc    = ais.rc
        self.dscc  = DatasetControllerClient(proc=ais)
        self.ac    = AssociationClient(proc=ais)
        self.sc    = SchedulerServiceClient(proc=ais)
        self.ing   = IngestionClient(proc=ais)
        
        #necessary to receive events i think
        self.pub   = ScheduleEventPublisher(process=ais)


    @defer.inlineCallbacks
    def update(self, msg_wrapped):
        """
        @brief update a data resource
        @param msg GPB, 9215/1,
        @GPB{Input,9215,1}
        @GPB{Returns,9216,1}
        @retval success
        """
        # check that the GPB is correct type & has a payload
        result = yield self._CheckRequest(msg_wrapped)
        if result != None:
            result.error_str = "AIS.ManageDataResource.update: " + result.error_str
            defer.returnValue(result)

        msg = msg_wrapped.message_parameters_reference 
        try:
            # Check only the type received and linked object types. All fields are
            #strongly typed in google protocol buffers!
            if not self._equalInputTypes(msg_wrapped, msg, UPDATE_DATA_RESOURCE_REQ_TYPE):
                errtext = "AIS.ManageDataResource.update: " + \
                    "Expected DataResourceUpdateRequest type, got " + str(msg)
                log.error(errtext)
                Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
                Response.error_num =  Response.ResponseCodes.BAD_REQUEST
                Response.error_str =  errtext
                defer.returnValue(Response)

            if not (msg.IsFieldSet("data_set_resource_id")):
                errtext = "AIS.ManageDataResource.update: " + \
                    "required fields not provided (data_set_resource_id)"
                log.error(errtext)
                Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
                Response.error_num =  Response.ResponseCodes.BAD_REQUEST
                Response.error_str =  errtext
                defer.returnValue(Response)

            if msg.IsFieldSet("visualization_url") and msg.visualization_url != '':
                urlRe = re.compile("([a-z](?:[-a-z0-9\+\.])*):(?:\/\/(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:])*@)?(\[(?:(?:(?:[0-9a-f]{1,4}:){6}(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|::(?:[0-9a-f]{1,4}:){5}(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:[0-9a-f]{1,4})?::(?:[0-9a-f]{1,4}:){4}(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:[0-9a-f]{1,4}:[0-9a-f]{1,4})?::(?:[0-9a-f]{1,4}:){3}(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:(?:[0-9a-f]{1,4}:){0,2}[0-9a-f]{1,4})?::(?:[0-9a-f]{1,4}:){2}(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:(?:[0-9a-f]{1,4}:){0,3}[0-9a-f]{1,4})?::[0-9a-f]{1,4}:(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:(?:[0-9a-f]{1,4}:){0,4}[0-9a-f]{1,4})?::(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:(?:[0-9a-f]{1,4}:){0,5}[0-9a-f]{1,4})?::[0-9a-f]{1,4}|(?:(?:[0-9a-f]{1,4}:){0,6}[0-9a-f]{1,4})?::)|v[0-9a-f]+[-a-z0-9\._~!\$&'\(\)\*\+,;=:]+)\]|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3}|(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=@])*)(?::[0-9]*)?(?:\/(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@]))*)*|\/(?:(?:(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@]))+)(?:\/(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@]))*)*)?|(?:(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@]))+)(?:\/(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@]))*)*|(?!(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@])))(?:\?(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@])|[\uE000-\uF8FF\uF0000-\uFFFFD|\u100000-\u10FFFD\/\?])*)?(?:\#(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@])|[\/\?])*)?", re.IGNORECASE)

                visualization_url = msg.visualization_url
                if (urlRe.match(visualization_url) is None):
                    errtext = "ManageDataResource.update(): " + \
                        "Visualization URL unexpected/invalid format: " + \
                        msg.visualization_url
                    log.error(errtext)
                    Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
                    Response.error_num =  Response.ResponseCodes.BAD_REQUEST
                    Response.error_str =  errtext
                    defer.returnValue(Response)

            #OOIION-164
            dateproblem = yield self._checkStartDatetime("ManageDataResource.update()", msg)
            if not dateproblem is None:
                defer.returnValue(dateproblem)
                

            dataset_resource = yield self.rc.get_instance(msg.data_set_resource_id)
            datasrc_resource = yield self._getOneAssociationSubject(dataset_resource, 
                                                                    HAS_A_ID, 
                                                                    DATASOURCE_RESOURCE_TYPE_ID)

            #watch for data inconsistency
            if datasrc_resource is None:
                errtext = "ManageDataResource.update(): " + \
                    "could not find a data source resource associated " + \
                    "with the data set at " + msg.data_set_resource_id
                log.info(errtext)
                Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)

                Response.error_num =  Response.ResponseCodes.NOT_FOUND
                Response.error_str =  errtext
                defer.returnValue(Response)
                
            
            if msg.IsFieldSet("update_interval_seconds"):

                #if we are rescheduling or turning off updates, delete scheduled events
                if 0 >= msg.update_interval_seconds or msg.IsFieldSet("update_start_datetime_millis"):
                    yield self._deleteAllScheduledEvents(datasrc_resource)
                    datasrc_resource.update_interval_seconds = 0
                    datasrc_resource.update_start_datetime_millis = 0

                # if update_interval is sane, create the new schedule
                if 0 < msg.update_interval_seconds and msg.IsFieldSet("update_start_datetime_millis"):
                    datasrc_resource.update_interval_seconds = msg.update_interval_seconds
                    datasrc_resource.update_start_datetime_millis = msg.update_start_datetime_millis

                    #get the things we need to set up the scheduler message
                    log.info("Looking up data set resource")
                    dataset_resource = yield self._getOneAssociationObject(datasrc_resource, 
                                                                           HAS_A_ID, 
                                                                           DATASET_RESOURCE_TYPE_ID)

                    # @TODO Must update the existing scheduled event if it exists!
                    # May have to delete and re add?

                    #dataset_id = dataset_resource.ResourceIdentity
                    sched_task = yield self._createScheduledEvent(msg.update_interval_seconds,
                                                                  msg.update_start_datetime_millis,
                                                                  dataset_resource.ResourceIdentity,
                                                                  datasrc_resource.ResourceIdentity)

                    #log.info("got this from scheduler: " + str(sched_task))

                    log.info("associating scheduler task info with this resource")
                    sched_task_rsrc = yield self.rc.create_instance(DATA_RESOURCE_SCHEDULED_TASK_TYPE,
                                                                    ResourceName="ScheduledTask resource")

                    sched_task_rsrc.task_id = sched_task.task_id
                    yield self.ac.create_association(datasrc_resource, HAS_A_ID, sched_task_rsrc)
                    sched_task_rsrc.ResourceLifeCycleState  = sched_task_rsrc.ACTIVE
                    yield self.rc.put_instance(sched_task_rsrc)
                    
            if msg.IsFieldSet("ion_title"):
                datasrc_resource.ion_title = msg.ion_title

            if msg.IsFieldSet("ion_description"):
                datasrc_resource.ion_description = msg.ion_description

            if msg.IsFieldSet("max_ingest_millis"):
                datasrc_resource.max_ingest_millis = msg.max_ingest_millis

            if msg.IsFieldSet("is_public"):
                datasrc_resource.is_public = msg.is_public
                if not msg.is_public:
                    datasrc_resource.ResourceLifeCycleState = datasrc_resource.ACTIVE
                    dataset_resource.ResourceLifeCycleState = dataset_resource.ACTIVE
                else:
                    datasrc_resource.ResourceLifeCycleState = datasrc_resource.COMMISSIONED
                    dataset_resource.ResourceLifeCycleState = dataset_resource.COMMISSIONED

            if msg.IsFieldSet("visualization_url") and msg.visualization_url != '':
                datasrc_resource.visualization_url = msg.visualization_url

            # This could be cleaned up to go faster - only call put if it is modified!
            yield self.rc.put_resource_transaction([datasrc_resource, dataset_resource])

        except ReceivedApplicationError, ex:
            log.info('AIS.ManageDataResource.update: Error: %s' %ex)
            Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
            Response.error_num =  ex.msg_content.MessageResponseCode
            Response.error_str =  "AIS.ManageDataResource.update: Error from lower-level service: " + \
                ex.msg_content.MessageResponseBody
            defer.returnValue(Response)

        Response = yield self.mc.create_instance(AIS_RESPONSE_MSG_TYPE)
        Response.result = 200
        Response.message_parameters_reference.add()
        Response.message_parameters_reference[0] = Response.CreateObject(UPDATE_DATA_RESOURCE_RSP_TYPE)
        Response.message_parameters_reference[0].success = True
        defer.returnValue(Response)


    @defer.inlineCallbacks
    def delete(self, msg_wrapped):
        """
        @brief delete a data resource
        @param msg GPB, 9213/1,
        @GPB{Input,9213,1}
        @GPB{Returns,9214,1}
        @retval success
        """
        # check that the GPB is correct type & has a payload
        result = yield self._CheckRequest(msg_wrapped)
        if result != None:
            result.error_str = "AIS.ManageDataResource.delete: " + result.error_str
            defer.returnValue(result)

        msg = msg_wrapped.message_parameters_reference 
        try:
            # Check only the type received and linked object types. All fields are
            #strongly typed in google protocol buffers!
            if not self._equalInputTypes(msg_wrapped, msg, DELETE_DATA_RESOURCE_REQ_TYPE):
                errtext = "AIS.ManageDataResource.delete: " + \
                    "Expected DataResourceDeleteRequest type, got " + str(msg)
                log.error(errtext)
                Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
                Response.error_num =  Response.ResponseCodes.BAD_REQUEST
                Response.error_str =  errtext
                defer.returnValue(Response)

            if not (msg.IsFieldSet("data_set_resource_id")):
                errtext = "AIS.ManageDataResource.delete: " + \
                    "required fields not provided (data_set_resource_id)"
                log.error(errtext)
                Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
                Response.error_num =  Response.ResponseCodes.BAD_REQUEST
                Response.error_str =  errtext
                defer.returnValue(Response)

            #store ids that were deleted, and return them later.
            deletions = []
            delete_resources = []
            for data_set_resource_id in msg.data_set_resource_id:

                #FIXME: if user does not own this data set, don't delete it

                log.info("Getting instance of data set resource with id = %s" % data_set_resource_id)
                dataset_resource = yield self.rc.get_instance(data_set_resource_id)
                log.info("Getting instance of datasource resource from association")
                datasrc_resource = yield self._getOneAssociationSubject(dataset_resource, 
                                                                       HAS_A_ID, 
                                                                       DATASOURCE_RESOURCE_TYPE_ID)

                log.info("got data src resource with id: %s" % datasrc_resource.ResourceIdentity)

                log.info("Deleting any attached scheduled ingest events")
                yield self._deleteAllScheduledEvents(datasrc_resource)

                log.info("Setting data source resource lifecycle = retired")
                datasrc_resource.ResourceLifeCycleState = datasrc_resource.RETIRED
                delete_resources.append(datasrc_resource)

                if not None is dataset_resource:
                    log.info("Setting data set resource lifecycle = retired")
                    dataset_resource.ResourceLifeCycleState = dataset_resource.RETIRED
                    delete_resources.append(dataset_resource)

                deletions.append(data_set_resource_id)

            log.info("putting all resource changes in one big transaction, " \
                         + str(len(delete_resources)))
            yield self.rc.put_resource_transaction(delete_resources)
            log.info("Success!")

        except ReceivedApplicationError, ex:
            log.info('AIS.ManageDataResource.delete: Error: %s' %ex)
            Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
            Response.error_num =  ex.msg_content.MessageResponseCode
            Response.error_str =  "AIS.ManageDataResource.delete: Error from lower-level service: " + \
                ex.msg_content.MessageResponseBody
            defer.returnValue(Response)

        Response = yield self.mc.create_instance(AIS_RESPONSE_MSG_TYPE)
        Response.result = 200
        Response.message_parameters_reference.add()
        Response.message_parameters_reference[0] = Response.CreateObject(DELETE_DATA_RESOURCE_RSP_TYPE)
        for d in deletions:
            Response.message_parameters_reference[0].successfully_deleted_id.append(d)

        defer.returnValue(Response)

    
    @defer.inlineCallbacks
    def create(self, msg_wrapped):
        """
        @brief create a data resource.  URL IS ASSUMED TO BE VALID NETCDF
        @param msg GPB, 9211/1,
        @GPB{Input,9211,1}
        @GPB{Returns,9212,1}
        @retval IDs of new objects, GPB 9212/1, otherwise an AIS error GPB
        """
        log.info('ManageDataResource.create()\n')

        my_datasrc_id      = None
        my_dataset_id      = None

        datasrc_resource      = None
        dataset_resource      = None

        # check that the GPB is correct type & has a payload
        result = yield self._CheckRequest(msg_wrapped)
        if result != None:
            result.error_str = "AIS.ManageDataResource.create: " + result.error_str
            defer.returnValue(result)

        msg = msg_wrapped.message_parameters_reference 
        try:
            # Check only the type received and linked object types. All fields are
            #strongly typed in google protocol buffers!
            if not self._equalInputTypes(msg_wrapped, msg, CREATE_DATA_RESOURCE_REQ_TYPE):
                errtext = "AIS.ManageDataResource.create: " + \
                    "Expected DataResourceCreateRequest type, got " + str(msg)
                log.error(errtext)
                Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
                Response.error_num =  Response.ResponseCodes.BAD_REQUEST
                Response.error_str =  errtext
                defer.returnValue(Response)

            # make user at least PRETEND to make an effort in filling out fields
            missing = self._missingResourceRequestFields(msg)
            # unless nothing is missing, error.
            if "" != missing:
                errtext = "AIS.ManageDataResource.create: " + \
                    "Missing/incorrect required fields in DataResourceCreateRequest: " + missing
                log.error(errtext)
                Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
                Response.error_num =  Response.ResponseCodes.BAD_REQUEST
                Response.error_str =  errtext
                defer.returnValue(Response)

            #max_ingest_millis: default to 30000 (30 seconds before ingest timeout)
            #FIXME: find out what that default should really be.
            if not msg.IsFieldSet("max_ingest_millis") or msg.max_ingest_millis <= 0:
                if msg.IsFieldSet("update_interval_seconds") and msg.update_interval_seconds > 1:
                    msg.max_ingest_millis = (msg.update_interval_seconds - 1) * 1000
                else:
                    msg.max_ingest_millis = DEFAULT_MAX_INGEST_MILLIS

            #OOIION-164
            dateproblem = yield self._checkStartDatetime("ManageDataResource.create()", msg)
            if not dateproblem is None:
                defer.returnValue(dateproblem)

            if msg.IsFieldSet("visualization_url") and msg.visualization_url != '':
                urlRe = re.compile("([a-z](?:[-a-z0-9\+\.])*):(?:\/\/(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:])*@)?(\[(?:(?:(?:[0-9a-f]{1,4}:){6}(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|::(?:[0-9a-f]{1,4}:){5}(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:[0-9a-f]{1,4})?::(?:[0-9a-f]{1,4}:){4}(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:[0-9a-f]{1,4}:[0-9a-f]{1,4})?::(?:[0-9a-f]{1,4}:){3}(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:(?:[0-9a-f]{1,4}:){0,2}[0-9a-f]{1,4})?::(?:[0-9a-f]{1,4}:){2}(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:(?:[0-9a-f]{1,4}:){0,3}[0-9a-f]{1,4})?::[0-9a-f]{1,4}:(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:(?:[0-9a-f]{1,4}:){0,4}[0-9a-f]{1,4})?::(?:[0-9a-f]{1,4}:[0-9a-f]{1,4}|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3})|(?:(?:[0-9a-f]{1,4}:){0,5}[0-9a-f]{1,4})?::[0-9a-f]{1,4}|(?:(?:[0-9a-f]{1,4}:){0,6}[0-9a-f]{1,4})?::)|v[0-9a-f]+[-a-z0-9\._~!\$&'\(\)\*\+,;=:]+)\]|(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])(?:\.(?:[0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])){3}|(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=@])*)(?::[0-9]*)?(?:\/(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@]))*)*|\/(?:(?:(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@]))+)(?:\/(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@]))*)*)?|(?:(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@]))+)(?:\/(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@]))*)*|(?!(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@])))(?:\?(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@])|[\uE000-\uF8FF\uF0000-\uFFFFD|\u100000-\u10FFFD\/\?])*)?(?:\#(?:(?:%[0-9a-f][0-9a-f]|[-a-z0-9\._~\uA0-\uD7FF\uF900-\uFDCF\uFDF0-\uFFEF\u10000-\u1FFFD\u20000-\u2FFFD\u30000-\u3FFFD\u40000-\u4FFFD\u50000-\u5FFFD\u60000-\u6FFFD\u70000-\u7FFFD\u80000-\u8FFFD\u90000-\u9FFFD\uA0000-\uAFFFD\uB0000-\uBFFFD\uC0000-\uCFFFD\uD0000-\uDFFFD\uE1000-\uEFFFD!\$&'\(\)\*\+,;=:@])|[\/\?])*)?", re.IGNORECASE)

                visualization_url = msg.visualization_url
                if (urlRe.match(visualization_url) is None):
                    errtext = "ManageDataResource.create(): " + \
                        "Visualization URL unexpected/invalid format: " + \
                        msg.visualization_url
                    log.error(errtext)
                    Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
                    Response.error_num =  Response.ResponseCodes.BAD_REQUEST
                    Response.error_str =  errtext
                    defer.returnValue(Response)

            # get user resource so we can associate it later
            user_resource = yield self.rc.get_instance(msg.user_id)

            # create the data source from the fields in the input message
            datasrc_resource = yield self._createDataSourceResource(msg)
            my_datasrc_id = datasrc_resource.ResourceIdentity

            # create the dataset by sending a blank message to the dscc
            log.info("manage_data_resource calling create dataset")
            dataset_req = yield self.mc.create_instance(None)
            # we get back the ID, so look up resource from that
            tmp = yield self.dscc.create_dataset_resource(dataset_req)
            my_dataset_id = tmp.key
            dataset_resource = yield self.rc.get_instance(my_dataset_id)
            log.info("created data set ") # + str(dataset_resource))

            # create topics
            topics_msg = yield self.mc.create_instance(INGESTER_CREATETOPICS_REQ_MSG)
            topics_msg.dataset_id = my_dataset_id
            #don't yield on this.
            self.ing.create_dataset_topics(topics_msg)

            #make associations
            yield self.ac.create_association(user_resource,    HAS_A_ID, datasrc_resource)
            association_d = yield self.ac.create_association(datasrc_resource, HAS_A_ID, dataset_resource)

            #build transaction
            resource_transaction = [datasrc_resource, dataset_resource]

            if (msg.IsFieldSet("update_interval_seconds") and \
                    msg.IsFieldSet("update_start_datetime_millis") and \
                    msg.update_interval_seconds > 0):

                #record values
                datasrc_resource.update_interval_seconds       = msg.update_interval_seconds
                datasrc_resource.update_start_datetime_millis  = msg.update_start_datetime_millis

                # set up the scheduled task
                sched_task = yield self._createScheduledEvent(msg.update_interval_seconds,
                                                              msg.update_start_datetime_millis,
                                                              my_dataset_id,
                                                              my_datasrc_id)
                #log.info("got this from scheduler: " + str(sched_task))

                sched_task_rsrc = yield self.rc.create_instance(DATA_RESOURCE_SCHEDULED_TASK_TYPE,
                                                                ResourceName="ScheduledTask resource")

                sched_task_rsrc.task_id = sched_task.task_id
                yield self.ac.create_association(datasrc_resource, HAS_A_ID, sched_task_rsrc)
                sched_task_rsrc.ResourceLifeCycleState  = sched_task_rsrc.ACTIVE
                resource_transaction.append(sched_task_rsrc)

            #these start new, and get set on the first ingest event
            datasrc_resource.ResourceLifeCycleState = datasrc_resource.NEW
            dataset_resource.ResourceLifeCycleState = dataset_resource.NEW

            yield self.rc.put_resource_transaction(resource_transaction)

            yield self._createEvent(my_dataset_id, my_datasrc_id)

        except ReceivedApplicationError, ex:
            log.info('AIS.ManageDataResource.create: Error from a lower-level service: %s' %ex)

            #mark lifecycle states
            datasrc_resource.ResourceLifeCycleState = datasrc_resource.RETIRED
            dataset_resource.ResourceLifeCycleState = dataset_resource.RETIRED
            sched_task_rsrc.ResourceLifeCycleState  = sched_task_rsrc.RETIRED
            yield self.rc.put_resource_transaction([datasrc_resource, dataset_resource, sched_task_rsrc])

            Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
            Response.error_num =  ex.msg_content.MessageResponseCode
            Response.error_str =  "AIS.ManageDataResource.create: Error from lower-level service: " + \
                ex.msg_content.MessageResponseBody
            defer.returnValue(Response)

        Response = yield self.mc.create_instance(AIS_RESPONSE_MSG_TYPE)
        Response.result = 200
        Response.message_parameters_reference.add()
        Response.message_parameters_reference[0] = Response.CreateObject(CREATE_DATA_RESOURCE_RSP_TYPE)
        Response.message_parameters_reference[0].data_source_id  = my_datasrc_id
        Response.message_parameters_reference[0].data_set_id     = my_dataset_id
        Response.message_parameters_reference[0].association_id  = association_d.AssociationIdentity
        defer.returnValue(Response)


    @defer.inlineCallbacks
    def _createEvent(self, dataset_id, datasource_id):
        """
        @brief create a single ingest event trigger and send it
        """
        log.info("triggering an immediate ingest event")
        msg = yield self.pub.create_event(origin=SCHEDULE_TYPE_PERFORM_INGESTION_UPDATE,
                                          task_id="manage_data_resource_FAKED_TASK_ID")
        
        msg.additional_data.payload = msg.CreateObject(SCHEDULER_PERFORM_INGEST)
        msg.additional_data.payload.dataset_id     = dataset_id
        msg.additional_data.payload.datasource_id  = datasource_id

        yield self.pub.publish_event(msg, origin=SCHEDULE_TYPE_PERFORM_INGESTION_UPDATE)


    @defer.inlineCallbacks
    def _createScheduledEvent(self, interval, start_time, dataset_id, datasource_id):
        """
        @brief create a scheduled event and return its task_id
        """
        log.info("Creating scheduler task")

        log.info("Creating add-request for scheduler")
        req_msg = yield self.mc.create_instance(SCHEDULER_ADD_REQ_TYPE)
        req_msg.interval_seconds       = interval
        req_msg.start_time             = start_time
        req_msg.desired_origin = SCHEDULE_TYPE_PERFORM_INGESTION_UPDATE

        req_msg.payload                = req_msg.CreateObject(SCHEDULER_PERFORM_INGEST)
        req_msg.payload.dataset_id     = dataset_id
        req_msg.payload.datasource_id  = datasource_id

        log.info("sending request to scheduler")
        response = yield self.sc.add_task(req_msg)
        log.info("got response")
        defer.returnValue(response)


    @defer.inlineCallbacks
    def _deleteAllScheduledEvents(self, data_source_resource):
        """
        @brief delete any scheduled events from scheduler and storage
        """

        log.info("Getting instances of scheduled task resources associated with this data source: %s"
                 % data_source_resource.ResourceIdentity)
        while True:
            sched_task_rsrc = yield self._getOneAssociationObject(data_source_resource, 
                                                                  HAS_A_ID, 
                                                                  DATARESOURCE_SCHEDULE_TYPE_ID)

            #how we exit
            if None is sched_task_rsrc: 
                log.info("No scheduled ingest events found")
                defer.returnValue(None)
            
            req_msg = yield self.mc.create_instance(SCHEDULER_DEL_REQ_TYPE)
            req_msg.task_id = sched_task_rsrc.task_id
            response = yield self.sc.rm_task(req_msg)
            log.debug("not sure what to do with the response: %s" % str(type(response)))
            #fixme: anything to do with this response?  i don't know of anything...
            sched_task_rsrc.ResourceLifeCycleState = sched_task_rsrc.RETIRED
            yield self.rc.put_instance(sched_task_rsrc)


    @defer.inlineCallbacks
    def _createDataSourceResource(self, msg):
        """
        @brief create a data resource
        @param msg GPB, 9211/1,
        @GPB{Input,9211,1}
        @retval data source resource
        """
        log.info('ManageDataResource._createDataSourceResource()\n')
        datasrc_resource = yield self.rc.create_instance(SA_DATASOURCE_RESOURCE_MSG,
                                                         ResourceName='Data Source Resource')

        #FILL UP FIELDS, lists followed by scalars
        datasrc_resource.property.extend(msg.property)
        datasrc_resource.station_id.extend(msg.station_id)

        datasrc_resource.source_type                   = msg.source_type
        datasrc_resource.request_type                  = msg.request_type
        datasrc_resource.request_bounds_north          = msg.request_bounds_north
        datasrc_resource.request_bounds_south          = msg.request_bounds_south
        datasrc_resource.request_bounds_west           = msg.request_bounds_west
        datasrc_resource.request_bounds_east           = msg.request_bounds_east
        datasrc_resource.base_url                      = msg.base_url
        datasrc_resource.dataset_url                   = msg.dataset_url
        datasrc_resource.ncml_mask                     = msg.ncml_mask
        datasrc_resource.max_ingest_millis             = msg.max_ingest_millis
        datasrc_resource.ion_title                     = msg.ion_title
        datasrc_resource.ion_description               = msg.ion_description
        datasrc_resource.ion_institution_id            = msg.ion_institution_id
        datasrc_resource.update_start_datetime_millis  = msg.update_start_datetime_millis
        datasrc_resource.is_public                     = msg.is_public
        datasrc_resource.visualization_url             = msg.visualization_url

        # from bug OOIION-131
        datasrc_resource.initial_starttime_offset_millis  = msg.initial_starttime_offset_millis
        datasrc_resource.starttime_offset_millis          = msg.starttime_offset_millis
        datasrc_resource.endtime_offset_millis            = msg.endtime_offset_millis
        datasrc_resource.aggregation_rule                 = msg.aggregation_rule

        for i, r in enumerate(msg.sub_ranges):
            s = datasrc_resource.sub_ranges.add()
            s.dim_name    = r.dim_name
            s.start_index = r.start_index
            s.end_index   = r.end_index

        if msg.IsFieldSet('authentication'):
            log.info("Setting datasource: authentication")
            datasrc_resource.authentication                = msg.authentication

        if msg.IsFieldSet('search_pattern'):
            log.info("Setting datasource: search_pattern")
            datasrc_resource.search_pattern                = msg.search_pattern

        datasrc_resource.registration_datetime_millis  = IonTime().time_ms

        #put it with the others
        yield self.rc.put_instance(datasrc_resource)
        log.info("created data source ") # + str(datasrc_resource))

        defer.returnValue(datasrc_resource)


    @defer.inlineCallbacks
    def _getOneAssociationObject(self, the_subject, the_predicate, the_object_type):
        """
        @brief get the subject side of an association when you only expect one
        @return id of what you're after
        """

        #can also do obj=
        found = yield self.ac.find_associations(subject=the_subject, \
                                                predicate_or_predicates=HAS_A_ID)

        association = None
        for a in found:
            mystery_resource = yield self.rc.get_instance(a.ObjectReference.key)
            mystery_resource_type = mystery_resource.ResourceTypeID.key
            log.info("Checking mystery resource %s " % mystery_resource.ResourceIdentity)
            log.info("Want type %s, got type %s" 
                     % (the_object_type, mystery_resource_type))
            if the_object_type == mystery_resource.ResourceTypeID.key:
                if not mystery_resource.RETIRED == mystery_resource.ResourceLifeCycleState:
                    #FIXME: if not association is None then we have data inconsistency!
                    association = a

        #this is an error case!
        if None is association:
            defer.returnValue(None)

        the_resource = yield self.rc.get_associated_resource_object(association)
        defer.returnValue(the_resource)


    @defer.inlineCallbacks
    def _getOneAssociationSubject(self, the_object, the_predicate, the_subject_type):
        """
        @brief get the subject side of an association when you only expect one
        @return id of what you're after
        """

        #can also do subject=
        found = yield self.ac.find_associations(obj=the_object, \
                                                predicate_or_predicates=HAS_A_ID)

        association = None
        for a in found:
            mystery_resource = yield self.rc.get_instance(a.SubjectReference.key)
            mystery_resource_type = mystery_resource.ResourceTypeID.key
            log.info("Checking mystery resource %s " % mystery_resource.ResourceIdentity)
            log.info("Want type %s, got type %s" 
                     % (the_subject_type, mystery_resource_type))
            if the_subject_type == mystery_resource.ResourceTypeID.key:
                if mystery_resource.RETIRED == mystery_resource.ResourceLifeCycleState:
                    log.info("FOUND ONE, but it's retired")
                else:
                    #FIXME: if not association is None then we have data inconsistency!
                    association = a

        #this is an error case!
        if None is association:
            defer.returnValue(None)

        the_resource = yield self.rc.get_associated_resource_subject(association)
        defer.returnValue(the_resource)


    def _missingResourceRequestFields(self, msg):
        """
        @brief make sure that all the required fields are set
        @return string empty string for no errors or message describing the unset fields
        """

        #this seems very un-GPB-ish, to have to check fields...
        req_fields = ["user_id",
                      "source_type",
                      "request_type",
                      #"request_bounds_north",
                      #"request_bounds_south",
                      #"request_bounds_west",
                      #"request_bounds_east",
                      #"ncml_mask",
                      #"max_ingest_millis",
                      "ion_title",
                      "ion_description",
                      "ion_institution_id",
                      #"update_interval_seconds",
                      #"update_start_datetime_millis",
                      "is_public",
                      ]

        #these repeated fields don't need to be set either
        #repeated string property = 3;
        #repeated string station_id = 4;

        #check em
        ret = ""

        if msg.IsFieldSet("base_url") and msg.IsFieldSet("dataset_url"):
            ret = "ONLY ONE OF (base_url, dataset_url)"
        elif not (msg.IsFieldSet("base_url") or msg.IsFieldSet("dataset_url")):
            ret = "ONE OF (base_url, dataset_url)"

        for f in req_fields:
            if not msg.IsFieldSet(f):
                if "" == ret:
                    ret = f
                else:
                    ret = ret + ", " + f

        return ret


    def _equalInputTypes(self, ais_req_msg, some_casref, desired_type):
        test_msg = ais_req_msg.CreateObject(desired_type)
        return (type(test_msg) == type(some_casref))
        

    @defer.inlineCallbacks
    def _CheckRequest(self, request):
       # Check for correct request protocol buffer type
       if request.MessageType != AIS_REQUEST_MSG_TYPE:
          # build AIS error response
          Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE, MessageName='AIS error response')
          Response.error_num = Response.ResponseCodes.BAD_REQUEST
          Response.error_str = 'Bad message type receieved, ignoring'
          defer.returnValue(Response)
 
       # Check payload in message
       if not request.IsFieldSet('message_parameters_reference'):
          # build AIS error response
          Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE, MessageName='AIS error response')
          Response.error_num = Response.ResponseCodes.BAD_REQUEST
          Response.error_str = "Required field [message_parameters_reference] not found in message"
          defer.returnValue(Response)
   
       defer.returnValue(None)


    #OOIION-164: check that the start date is less than a year from now
    @defer.inlineCallbacks
    def _checkStartDatetime(self, caller, msg):
        if msg.IsFieldSet("update_start_datetime_millis") \
                and msg.update_start_datetime_millis > ((time.time() + 31536000) * 1000):
            errtext = caller + ": Got a start date in milliseconds that was more than 1 year in the future ("
            errtext = errtext + str(msg.update_start_datetime_millis) + ")."  
            log.error(errtext)
            Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE)
            Response.error_num =  Response.ResponseCodes.BAD_REQUEST
            Response.error_str =  errtext
            defer.returnValue(Response)

        defer.returnValue(None)
