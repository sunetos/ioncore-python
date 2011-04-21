import ion.util.ionlog
log = ion.util.ionlog.getLogger(__name__)

from twisted.internet import defer, reactor
from ion.core.process.service_process import ServiceProcess, ServiceClient
from ion.core.process.process import ProcessFactory

class EPUControllerClient(ServiceClient):
    """
    Client for sending messages directly to an EPU Controller
    """
    def __init__(self, proc=None, **kwargs):
        log.debug('EPUControllerClient.__init__: kwargs='+str(kwargs))
        if not 'targetname' in kwargs:
            kwargs['targetname'] = "epu_controller"
        ServiceClient.__init__(self, proc, **kwargs)

    @defer.inlineCallbacks
    def reconfigure(self, newconf):
        """Triggers a reconfigure option.  This might not be implemented by
        the decision engine implementation that the EPU Controller is
        configured with.  The new configuration is interpreted in a very
        specific way, see the comments and/or documentation for the EPU
        controller (and in particular the decision engine that it is
        expected to be implemented with).
        
        @param newconf None or dict of key/value pairs
        """
        log.debug("Sending reconfigure request to EPU controller: '%s'" % self.target)
        yield self.send('reconfigure', newconf)

    @defer.inlineCallbacks
    def reconfigure_rpc(self, newconf):
        """See reconfigure()
        """
        yield self.rpc_send('reconfigure_rpc', newconf)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def de_state(self):
        (content, headers, msg) = yield self.rpc_send('de_state', {})
        log.debug('DE state reply: '+str(content))
        defer.returnValue(str(content))

    """
    @defer.inlineCallbacks
    def whole_state(self):
        (content, headers, msg) = yield self.rpc_send('whole_state', {})
        defer.returnValue(content)
    """

    def whole_state(self):
        de_state = 'STABLE_DE'   # from epu/epucontroller/de_states.py
        # following from epu/decisionengine/impls/npreserving.py & pu/decisionengine/impls/default_engine.py
        de_conf_report = "NpreservingEngine: preserves %d instances (%d unique), sites: %s, types: %s, allocations: %s" \
                    % (2, 1, ["ec2-east"], ["epu_work_consumer"], ["small"])
        instances = {"instance_id_01" : {"iaas_state" : '600-RUNNING',       # from epu/states.py
                                         "iaas_state_time" : 1293833966,
                                         "heartbeat_time" : 1293833967,
                                         "heartbeat_state" : "OK"             # from pu/epucontroller/health.py
                                         },
                     "instance_id_02" : {"iaas_state" : '500-STARTED',       # from epu/states.py
                                         "iaas_state_time" : 1293833968,
                                         "heartbeat_time" : 1293833969,
                                         "heartbeat_state" : "ZOMBIE"             # from pu/epucontroller/health.py
                                         }}
        return {"de_state": de_state,
                "de_conf_report": de_conf_report,
                "last_queuelen_size": 2,
                "last_queuelen_time": 1293833966,   # ~ number of seconds since 1970
                "instances": instances}


    @defer.inlineCallbacks
    def node_error(self, node_id):
        (content, headers, msg) = yield self.rpc_send('node_error', node_id)
        defer.returnValue(content)
