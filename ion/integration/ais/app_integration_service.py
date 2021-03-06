#!/usr/bin/env python

"""
@file ion/integration/app_integration_service.py
@author David Everett
@brief Core service frontend for Application Integration Services 
"""

import ion.util.ionlog
log = ion.util.ionlog.getLogger(__name__)
import logging
from twisted.internet import defer
import time

from ion.core.object import object_utils
from ion.core.process.process import ProcessFactory
from ion.core.process.service_process import ServiceProcess, ServiceClient
from ion.services.coi.resource_registry.resource_client import ResourceClient
from ion.core.messaging.message_client import MessageClient

# import GPB type identifiers for AIS
from ion.integration.ais.ais_object_identifiers import AIS_REQUEST_MSG_TYPE, \
                                                       AIS_RESPONSE_ERROR_TYPE

# import working classes for AIS
from ion.integration.ais.common.metadata_cache import  MetadataCache
from ion.integration.ais.findDataResources.findDataResources import FindDataResources, \
    DataResourceUpdateEventSubscriber
from ion.integration.ais.getDataResourceDetail.getDataResourceDetail import GetDataResourceDetail
from ion.integration.ais.createDownloadURL.createDownloadURL import CreateDownloadURL
from ion.integration.ais.RegisterUser.RegisterUser import RegisterUser
from ion.integration.ais.ManageResources.ManageResources import ManageResources
from ion.integration.ais.manage_data_resource.manage_data_resource import ManageDataResource
from ion.integration.ais.validate_data_resource.validate_data_resource import ValidateDataResource
from ion.integration.ais.manage_data_resource_subscription.manage_data_resource_subscription import ManageDataResourceSubscription


addresslink_type = object_utils.create_type_identifier(object_id=20003, version=1)
person_type = object_utils.create_type_identifier(object_id=20001, version=1)


class AppIntegrationService(ServiceProcess):
    """
    Service to provide clients access to backend data
    """
    # Declaration of service
    declare = ServiceProcess.service_declare(name='app_integration',
                                             version='0.1.0',
                                             dependencies=[])

    # set to None to turn off timing logging, set to anything else to turn on timing logging
    AnalyzeTiming = None
    
    class TimeStampsClass (object):
        pass
    
    TimeStamps = TimeStampsClass()
    
    def TimeStamp (self):
        TimeNow = time.time()
        TimeStampStr = "(wall time = " + str (TimeNow) + \
                       ", elapse time = " + str(TimeNow - self.TimeStamps.StartTime) + \
                       ", delta time = " + str(TimeNow - self.TimeStamps.LastTime) + \
                       ")"
        self.TimeStamps.LastTime = TimeNow
        return TimeStampStr
    

    def __init__(self, *args, **kwargs):

        ServiceProcess.__init__(self, *args, **kwargs)

        self.rc = ResourceClient(proc = self)
        self.mc = MessageClient(proc = self)
    
        log.debug('AppIntegrationService.__init__()')


    @defer.inlineCallbacks
    def slc_init(self):
        self.metadataCache = MetadataCache(self)
        log.debug('Instantiated AIS Metadata Cache Object')
        yield self.metadataCache.loadDataSets()
        yield self.metadataCache.loadDataSources()

        log.debug('instantiating DataResourceUpdateEventSubscriber')
        self.subscriber = DataResourceUpdateEventSubscriber(self, process = self)
        self.register_life_cycle_object(self.subscriber)
        
        # create worker instances
        self.FindDataResourcesWorker = FindDataResources(self)
        self.GetDataResourceDetailWorker = GetDataResourceDetail(self)       
        self.CreateDownloadURLWorker = CreateDownloadURL(self)
        self.RegisterUserWorker = RegisterUser(self)
        self.ManageResourcesWorker = ManageResources(self)
        self.ManageDataResourcWworker = ManageDataResource(self)
        self.ValidateDataResourceWorker = ValidateDataResource(self)
        self.ManageDataResourceSubscriptionWorker = ManageDataResourceSubscription(self)
        
        
    def getMetadataCache(self):
        return self.metadataCache

    @defer.inlineCallbacks
    def op_findDataResources(self, content, headers, msg):
        """
        @brief Find data resources that have been published, regardless
        of owner.
        @param GPB optional spatial and temporal bounds.
        @retval GPB with list of resource IDs.
        """

        log.debug('op_findDataResources service method.')
        returnValue = yield self.FindDataResourcesWorker.findDataResources(content)
        yield self.reply_ok(msg, returnValue)

    @defer.inlineCallbacks
    def op_findDataResourcesByUser(self, content, headers, msg):
        """
        @brief Find data resources associated with given userID,
        regardless of life cycle state.
        @param GPB containing OOID user ID, and option spatial and temporal
        bounds.
        @retval GPB with list of resource IDs.
        """

        log.debug('op_findDataResourcesByUser service method.')
        returnValue = yield self.FindDataResourcesWorker.findDataResourcesByUser(content)
        yield self.reply_ok(msg, returnValue)

    @defer.inlineCallbacks
    def op_getDataResourceDetail(self, content, headers, msg):
        """
        @brief Get detailed metadata for a given resource ID.
        @param GPB containing resource ID.
        @retval GPB containing detailed metadata.
        """

        log.info('op_getDataResourceDetail service method')
        returnValue = yield self.GetDataResourceDetailWorker.getDataResourceDetail(content)
        yield self.reply_ok(msg, returnValue)

    @defer.inlineCallbacks
    def op_createDownloadURL(self, content, headers, msg):
        """
        @brief Create download URL for given resource ID.
        @param GPB containing resource ID.
        @retval GPB containing download URL.
        """

        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_createDownloadURL: '+str(content))
        returnValue = yield self.CreateDownloadURLWorker.createDownloadURL(content)
        yield self.reply_ok(msg, returnValue)   

    @defer.inlineCallbacks
    def op_registerUser(self, content, headers, msg):
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_registerUser: \n'+str(content))
        response = yield self.RegisterUserWorker.registerUser(content);
        yield self.reply_ok(msg, response)
        
    @defer.inlineCallbacks
    def op_updateUserProfile(self, content, headers, msg):
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_updateUserProfile: \n'+str(content))
        response = yield self.RegisterUserWorker.updateUserProfile(content);
        yield self.reply_ok(msg, response)
        
    @defer.inlineCallbacks
    def op_getUser(self, content, headers, msg):
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_getUser: \n'+str(content))
        response = yield self.RegisterUserWorker.getUser(content);
        yield self.reply_ok(msg, response)
        
    def getTestDatasetID(self):
        return self.dsID
                         
    @defer.inlineCallbacks
    def op_getResourceTypes(self, content, headers, msg):
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_getResourceTypes: \n'+str(content))
        response = yield self.ManageResourcesWorker.getResourceTypes(content);
        yield self.reply_ok(msg, response)

    @defer.inlineCallbacks
    def op_getResourcesOfType(self, content, headers, msg):
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_getResourcesOfType: \n'+str(content))
        response = yield self.ManageResourcesWorker.getResourcesOfType(content);
        yield self.reply_ok(msg, response)


    @defer.inlineCallbacks
    def op_getResource(self, content, headers, msg):
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_getResource: \n'+str(content))
        response = yield self.ManageResourcesWorker.getResource(content);
        yield self.reply_ok(msg, response)


    @defer.inlineCallbacks
    def op_createDataResource(self, content, headers, msg):
        """
        @brief create a new data resource
        """
        log.debug('op_createDataResource: \n'+str(content))
        response = yield self.ManageDataResourcWworker.create(content);
        yield self.reply_ok(msg, response)

    @defer.inlineCallbacks
    def op_updateDataResource(self, content, headers, msg):
        """
        @brief create a new data resource
        """
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_updateDataResource: \n'+str(content))
        response = yield self.ManageDataResourcWworker.update(content);
        yield self.reply_ok(msg, response)

    @defer.inlineCallbacks
    def op_deleteDataResource(self, content, headers, msg):
        """
        @brief create a new data resource
        """
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_deleteDataResource: \n'+str(content))
        response = yield self.ManageDataResourcWworker.delete(content);
        yield self.reply_ok(msg, response)

    @defer.inlineCallbacks
    def op_validateDataResource(self, content, headers, msg):
        """
        @brief validate a data resource URL
        """
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_validateDataResource: \n'+str(content))
        response = yield self.ValidateDataResourceWorker.validate(content);
        yield self.reply_ok(msg, response)


    @defer.inlineCallbacks
    def op_createDataResourceSubscription(self, content, headers, msg):
        """
        @brief subscribe to a data resource
        """
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_createDataResourceSubscription: \n'+str(content))
        response = yield self.ManageDataResourceSubscriptionWorker.create(content);
        yield self.reply_ok(msg, response)

    @defer.inlineCallbacks
    def op_findDataResourceSubscriptions(self, content, headers, msg):
        """
        @brief find subscriptions to a data resource
        """
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_findDataResourceSubscriptions: \n'+str(content))
        response = yield self.ManageDataResourceSubscriptionWorker.find(content);
        yield self.reply_ok(msg, response)

    @defer.inlineCallbacks
    def op_deleteDataResourceSubscription(self, content, headers, msg):
        """
        @brief delete subscription to a data resource
        """
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_deleteDataResourceSubscription: \n'+str(content))
        response = yield self.ManageDataResourceSubscriptionWorker.delete(content);
        yield self.reply_ok(msg, response)

    @defer.inlineCallbacks
    def op_updateDataResourceSubscription(self, content, headers, msg):
        """
        @brief update subscription to a data resource
        """
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('op_updateDataResourceSubscription: \n'+str(content))
        response = yield self.ManageDataResourceSubscriptionWorker.update(content);
        yield self.reply_ok(msg, response)



class AppIntegrationServiceClient(ServiceClient):
    """
    This is a service client for AppIntegrationServices.
    """
    def __init__(self, proc=None, **kwargs):
        if not 'targetname' in kwargs:
            kwargs['targetname'] = "app_integration"
        ServiceClient.__init__(self, proc, **kwargs)
        self.mc = MessageClient(proc=proc)
        
    @defer.inlineCallbacks
    def findDataResources(self, message):
        yield self._check_init()
        log.debug("AppIntegrationServiceClient: findDataResources(): sending msg to AppIntegrationService.")
        (content, headers, payload) = yield self.rpc_send('findDataResources', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.info('Service reply: ' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def findDataResourcesByUser(self, message):
        yield self._check_init()
        log.debug("AppIntegrationServiceClient: findDataResourcesByUser(): sending msg to AppIntegrationService.")
        (content, headers, payload) = yield self.rpc_send('findDataResourcesByUser', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.info('Service reply: ' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def getDataResourceDetail(self, message):
        yield self._check_init()
        log.debug("AppIntegrationServiceClient: getDataResourceDetail(): sending msg to AppIntegrationService.")
        (content, headers, payload) = yield self.rpc_send('getDataResourceDetail', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.info('Service reply: ' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def createDownloadURL(self, message):
        yield self._check_init()
        result = yield self.CheckRequest(message)
        if result is not None:
            log.error('AIS.createDownloadURL: ' + result.error_str)
            defer.returnValue(result)
        # check that ooi_id is present in GPB
        if not message.message_parameters_reference.IsFieldSet('user_ooi_id'):
            # build AIS error response
            Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE, MessageName='AIS error response')
            Response.error_num = Response.ResponseCodes.BAD_REQUEST
            Response.error_str = "AIS.createDownloadURL: Required field [user_ooi_id] not found in message"
            log.error("Required field [user_ooi_id] not found in message")
            defer.returnValue(Response)
        log.debug("AppIntegrationServiceClient: createDownloadURL(): sending msg to AppIntegrationService.")
        (content, headers, payload) = yield self.rpc_send_protected('createDownloadURL',
                                                                    message,
                                                                    message.message_parameters_reference.user_ooi_id,
                                                                    "0")
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.info('Service reply: ' + str(content))
        defer.returnValue(content)
 
    @defer.inlineCallbacks
    def registerUser(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.registerUser: sending following message to registerUser:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('registerUser', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.registerUser: IR Service reply:\n' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def updateUserProfile(self, message):
        yield self._check_init()
        # check that the GPB is correct type & has a payload
        result = yield self.CheckRequest(message)
        if result is not None:
            log.error('AIS.updateUserProfile: ' + result.error_str)
            defer.returnValue(result)
        # check that ooi_id is present in GPB
        if not message.message_parameters_reference.IsFieldSet('user_ooi_id'):
            # build AIS error response
            Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE, MessageName='AIS error response')
            Response.error_num = Response.ResponseCodes.BAD_REQUEST
            Response.error_str = "AIS.updateUserProfile: Required field [user_ooi_id] not found in message (AIS)"
            log.error("Required field [user_ooi_id] not found in message")
            defer.returnValue(Response)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.updateUserProfile: sending following message to updateUserProfile:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send_protected('updateUserProfile',
                                                                    message,
                                                                    message.message_parameters_reference.user_ooi_id,
                                                                    "0")
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.updateUserProfile: IR Service reply:\n' + str(content))
        defer.returnValue(content)
              
    @defer.inlineCallbacks
    def getUser(self, message):
        yield self._check_init()
        # check that the GPB is correct type & has a payload
        result = yield self.CheckRequest(message)
        if result is not None:
            log.error('AIS.getUser: ' + result.error_str)
            defer.returnValue(result)
        # check that ooi_id is present in GPB
        if not message.message_parameters_reference.IsFieldSet('user_ooi_id'):
            # build AIS error response
            Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE, MessageName='AIS error response')
            Response.error_num = Response.ResponseCodes.BAD_REQUEST
            Response.error_str = "AIS.getUser: Required field [user_ooi_id] not found in message (AIS)"
            log.error("Required field [user_ooi_id] not found in message")
            defer.returnValue(Response)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.getUser: sending following message to getUser:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send_protected('getUser',
                                                                    message,
                                                                    message.message_parameters_reference.user_ooi_id,
                                                                    "0")
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.getUser: IR Service reply:\n' + str(content))
        defer.returnValue(content)
              
    @defer.inlineCallbacks
    def getResourceTypes(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.getResourceTypes: sending following message to getResourceTypes:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('getResourceTypes', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.getResourceTypes: AIS reply:\n' + str(content))
        defer.returnValue(content)
 
    @defer.inlineCallbacks
    def getResourcesOfType(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.getResourcesOfType: sending following message to getResourcesOfType:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('getResourcesOfType', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.getResourcesOfType: AIS reply:\n' + str(content))
        defer.returnValue(content)
 
    @defer.inlineCallbacks
    def getResource(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.getResource: sending following message to getResource:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('getResource', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.getResource: AIS reply:\n' + str(content))
        defer.returnValue(content)
 
    @defer.inlineCallbacks
    def createDataResource(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.createDataResource: sending following message to createDataResource:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('createDataResource', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.createDataResource: AIS reply:\n' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def updateDataResource(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.updateDataResource: sending following message to updateDataResource:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('updateDataResource', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.updateDataResource: AIS reply:\n' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def deleteDataResource(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.deleteDataResource: sending following message to deleteDataResource:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('deleteDataResource', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.deleteDataResource: AIS reply:\n' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def validateDataResource(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.validateDataResource: sending following message to validateDataResource:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('validateDataResource', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.validateDataResource: AIS reply:\n' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def createDataResourceSubscription(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.createDataResourceSubscription: sending following message:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('createDataResourceSubscription', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.createDataResourceSubscription: AIS reply:\n' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def findDataResourceSubscriptions(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.findDataResourceSubscriptions: sending following message:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('findDataResourceSubscriptions', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.findDataResourceSubscriptions: AIS reply:\n' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def deleteDataResourceSubscription(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.deleteDataResourceSubscription: sending following message:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('deleteDataResourceSubscription', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.deleteDataResourceSubscription: AIS reply:\n' + str(content))
        defer.returnValue(content)
        
    @defer.inlineCallbacks
    def updateDataResourceSubscription(self, message):
        yield self._check_init()
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("AIS_client.updateDataResourceSubscription: sending following message:\n%s" % str(message))
        (content, headers, payload) = yield self.rpc_send('updateDataResourceSubscription', message)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug('AIS_client.updateDataResourceSubscription: AIS reply:\n' + str(content))
        defer.returnValue(content)
        

    @defer.inlineCallbacks
    def CheckRequest(self, request):
        """
        @brief Check for correct request GPB type -- this is good for ALL AIS requests
        """
        if request.MessageType != AIS_REQUEST_MSG_TYPE:
            # build AIS error response
            Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE, MessageName='AIS error response')
            Response.error_num = Response.ResponseCodes.BAD_REQUEST
            Response.error_str = 'Bad message type received, ignoring'
            defer.returnValue(Response)

        # Check payload in message
        if not request.IsFieldSet('message_parameters_reference'):
            # build AIS error response
            Response = yield self.mc.create_instance(AIS_RESPONSE_ERROR_TYPE, MessageName='AIS error response')
            Response.error_num = Response.ResponseCodes.BAD_REQUEST
            Response.error_str = "Required field [message_parameters_reference] not found in message"
            defer.returnValue(Response)
  
        defer.returnValue(None)


# Spawn of the process using the module name
factory = ProcessFactory(AppIntegrationService)

