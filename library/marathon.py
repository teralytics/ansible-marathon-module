#!/usr/bin/env python
# -*- coding: utf-8 -*-

DOCUMENTATION = '''
module: marathon
short_description: Manages marathon applications
description:
    - Controls applications running on marathon and allows to create, destroy and update them. All information is taken from a json file describing the application (including the ID)

options:
  uri:
    required: true
    description:
      - URI of a Marathon node
  state:
    required: true
    description:
      - Desired state of the marathon application: - present: application is created if it doesn't exist, but it is not updated if the json changed - absent: application is destroyed - updated: application is updated if the json has differences with the existing configuration - test: outputs the diff between the submitted application and the one that is running (if any) - get: outputs the running application
      choices: ["present", "absent", "updated", "test", "get"]
  app_json:
    required: false
    description:
      - The JSON file describing the marathon application.  Either this or app is required for all the state choices, except 'get' and 'absent' (where not supplying it is OK).
  app_id:
    required: false
    description:
      - The id of the marathon application to 'get'.  Used when state is 'get' or 'absent'.
  app:
    required: false
    description:
      - The JSON content, as a string containing valid JSON, describing the marathon application.  Either this or app_json is required for all the state choices, except 'get' and 'absent' (where not supplying it is OK).
  force:
    required: false
    description:
      - If true, forces the application to be removed, even if it is locked due to ongoing changes.

author: "Vincenzo Pii (vincenzo.pii@teralytics.net)"
'''

# Note: the diff logic (of the test state) is not integrated with the tasks that (re-)deploy the application
# because it's difficult to determine if something changed because marathon added default
# fields to the application or if the deployment file actually differed.
# For example, marathon always adds the "privileged": false node under the docker node.

EXAMPLES = '''
# Ensures the application is running but doesn't update its configuration if the json has changed
- name: Create an application
  marathon: uri=http://marathon-node:8080 app_json='nginx.json' state=present

# Destroys the application
- name: Destroy an application
  marathon: uri=http://marathon-node:8080 app_json='nginx.json' state=absent

# Get an application's state info (or fails if no app found for the given id)
- name: Get application infos
  marathon: uri=http://marathon-node:8080 state=get app_id='nginx' app_json=''

'''

import json
try:
    import marathon
    import marathon.exceptions
    HAS_MARATHON = True
except ImportError:
    HAS_MARATHON = False
import time
import copy

class AppStatuses(object):

    def __init__(self):
        super(AppStatuses, self).__init__()

    APP_DEPLOYED = 0
    APP_NOT_PRESENT = 1

class MarathonAppManager(object):

    # Dict of keychains (nested keys to access elements of a dictionary)
    # that identify elements that we want to ignore when updating an application
    # with a new configuration
    UPDATE_IGNORE = {
      # The servicePort will be added by marathon even if it is not in our
      # configuration, so we ignore it when comparing old and new configuration
      # for updates
      'servicePort': ['container', 'docker', 'portMappings']
    }

    def __init__(self, uri, appid):
        super(MarathonAppManager, self).__init__()
        self._marathon_uri = uri
        self._appid = appid
        self._marathon_client = marathon.MarathonClient(uri)

    @staticmethod
    def _get_marathon_app_from_json(json_definition):
        return marathon.MarathonApp.from_json(json.loads(json_definition))

    # http://stackoverflow.com/questions/25851183/how-to-compare-two-json-objects-with-the-same-elements-in-a-different-order-equa
    @staticmethod
    def _ordered(obj):
        if isinstance(obj, dict):
            return sorted((k, MarathonAppManager._ordered(v)) for k, v in obj.items())
        if isinstance(obj, list):
            return sorted(MarathonAppManager._ordered(x) for x in obj)
        else:
            return obj

    # http://stackoverflow.com/a/36131992/528313
    @staticmethod
    def _get_nested_dict(dictionary, *keys):
        return reduce(lambda d, key: d.get(key) if d else None, keys, dictionary)

    @staticmethod
    def _clean_json_objects_for_update(dictionary):
        service_port_key = 'servicePort'
        nested = MarathonAppManager._get_nested_dict(dictionary, *(MarathonAppManager.UPDATE_IGNORE[service_port_key]))
        # If we find this, it's a list of portmappings
        if nested:
            for match in nested:
                if match.get(service_port_key):
                    del match[service_port_key]
        return

    def _get_app_info(self):
        try:
            app_info = self._marathon_client.get_app(self._appid)
        except marathon.exceptions.NotFoundError:
            return None
        return app_info

    def _sync_app_status(self, status, attempts=60, wait_seconds=3):
        '''
        Waits until the application is in the desired state (for a max number
        of attempts)
        '''
        if status == AppStatuses.APP_DEPLOYED:
            while self._get_app_info().tasks_running == 0 and attempts > 0:
                time.sleep(wait_seconds)
                attempts -= 1
        elif status == AppStatuses.APP_NOT_PRESENT:
            while self._get_app_info() and attempts > 0:
                time.sleep(wait_seconds)
                attempts -= 1
        if attempts == 0:
            raise Exception("Error while waiting for application to be in state {}".format(status))
        return

    def _fail_if_not_running(self):
        if self._get_app_info() is None:
            return module.fail_json(msg="Application with id {} could not be found on {}".format(self._appid, self._marathon_uri))

    def _fail_if_running(self):
        app_info = self._get_app_info()
        if app_info != None:
            return module.fail_json(msg="Application {} on {} exists: {}".format(self._appid, self._marathon_uri, app_info))

    def _compare_json_deployments(self, d1, d2):
        # Remove items that we want to ignore
        d1 = copy.deepcopy(d1)
        d2 = copy.deepcopy(d2)
        MarathonAppManager._clean_json_objects_for_update(d1)
        MarathonAppManager._clean_json_objects_for_update(d2)

        for item in marathon.MarathonApp.UPDATE_OK_ATTRIBUTES:
            if d1.get(item) and d2.get(item) and MarathonAppManager._ordered(d1[item]) != MarathonAppManager._ordered(d2[item]):
                # Found a difference
                return False
        # Items are the sames
        return True

    # _app_id is in the object
    def get_app(self):
        app_info = self._get_app_info()
        if app_info is None:
            module.fail_json(msg="Application with id {} could not be found on {}".format(self._appid, self._marathon_uri))
        else:
            module.exit_json(changed=False, meta=json.loads(app_info.to_json()))

    def create_app(self, json_definition):
        self._fail_if_running()
        app = MarathonAppManager._get_marathon_app_from_json(json_definition)
        try:
            self._marathon_client.create_app(self._appid, app)
        except marathon.exceptions.MarathonHttpError as e:
            module.fail_json(msg=e.error_message, details=e.error_details)
        self._sync_app_status(AppStatuses.APP_DEPLOYED)
        return self._get_app_info().to_json(), True

    def create_if_not_exists(self, json_definition):
        app_info = self._get_app_info()
        if app_info is None:
            ret, changed = self.create_app(json_definition)
            module.exit_json(changed=changed, meta=json.loads(ret))
        else:
            module.exit_json(changed=False, meta=json.loads(app_info.to_json()))

    def destroy_app(self, force=False):
        app_info = self._get_app_info()
        if app_info is None:
            module.exit_json(changed=False, meta=json.dumps(None))
        app_info = self._marathon_client.delete_app(self._appid, force=force)
        self._sync_app_status(AppStatuses.APP_NOT_PRESENT)
        if isinstance(app_info, basestring):
            module.exit_json(changed=True, meta=json.loads(app_info))
        module.exit_json(changed=True, **app_info)

    def update_app(self, json_definition):
        app_info = self._get_app_info()
        if app_info is None:
            ret, changed = self.create_app(json_definition)
            module.exit_json(changed=changed, meta=json.loads(ret))
        self._fail_if_not_running()
        # Compare the running version of the application with the submitted json
        app_json = app_info.to_json()
        app_object_json = json.loads(app_json)
        app_config_object_json = json.loads(MarathonAppManager._get_marathon_app_from_json(json_definition).to_json())
        if self._compare_json_deployments(app_object_json, app_config_object_json):
            # No need to update
            module.exit_json(changed=False, meta=json.loads(app_json))
        else:
            app = MarathonAppManager._get_marathon_app_from_json(json_definition)
            try:
                self._marathon_client.update_app(self._appid, app)
            except marathon.exceptions.MarathonHttpError as e:
                module.fail_json(msg=e.error_message, details=e.error_details)
            module.exit_json(changed=True, meta=json.loads(app_json))

    def diff_app(self, json_definition):
        deployed_app = self._get_app_info()
        if deployed_app:
            deployed_app_json_obj = json.loads(deployed_app.to_json())
        else:
            deployed_app_json_obj = json.loads('{}')
        json_definition_obj = json.loads(json_definition)
        string_old = json.dumps(deployed_app_json_obj, sort_keys=True, indent=4, separators=('', ': '))
        string_new = json.dumps(json_definition_obj, sort_keys=True, indent=4, separators=('', ': '))
        ansible_diff = {'before': string_old,
                        'after': string_new}
        module.exit_json(changed=True, meta=json.dumps(None), diff=ansible_diff)


def main():

    if not HAS_MARATHON:
        module.fail_json(msg='marathon python module required for this module')

    marathon_uri = module.params['uri'].rstrip('/')
    state = module.params['state']

    force = module.params['force']
    if force and state not in ['absent']:
        module.fail_json(msg="supplying force=true only works when state is 'absent'.")

    if module.params['app_json']:
        json_filename = module.params['app_json']
        app_json = ''
        with open(json_filename) as jf:
            app_json = jf.read()
        appid = json.loads(app_json)['id']
    elif module.params['app']:
        app_json = module.params['app']
        appid = json.loads(app_json)['id']
    elif module.params['app_id']:
        if state not in ["get", "absent"]:
            module.fail_json(msg="supplying app_id only works when state is 'get' or 'absent'.")
        appid = module.params['app_id']
    else:
        module.fail_json(msg="this module requires one of the app_json, app_id or app parameters.")

    mam = MarathonAppManager(marathon_uri, appid)

    ret = ''
    changed = False

    if state == 'present':
        ret, changed = mam.create_if_not_exists(app_json)
    elif state == 'absent':
        ret, changed = mam.destroy_app(force)
    elif state == 'updated':
        ret, changed = mam.update_app(app_json)
    elif state == 'test':
        ret, changed = mam.diff_app(app_json)
    elif state == 'get':
        ret, changed = mam.get_app()
    else:
        module.fail_json(msg="Unknown state: {}".format(state))

from ansible.module_utils.basic import *
from ansible.module_utils.urls import *

module = AnsibleModule(
    argument_spec=dict(
        uri=dict(required=True),
        app_json=dict(required=False),
        app=dict(required=False),
        app_id=dict(required=False),
        state=dict(required=True, choices=['present', 'absent', 'updated', 'test','get']),
        force=dict(required=False, type='bool', default=False),
    ),
)

if __name__ == "__main__":
    main()
