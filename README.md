# Ansible Role: marathon-deploy

An Ansible role that helps deploying applications on marathon.

The core of the role is a module to support an operation like

    - name: run application on marathon
      marathon: uri=http://marathon-node:8080 app_json='nginx.json' state=present

or like

    - name: run application on marathon
      marathon: uri=http://marathon-node:8080 app='{{ var_describing_app | to_json }}' state=present

## Requirements

The module shipping with the role is supposed to run on a node that can send
REST requests to the marathon endpoint. Typically this could be the localhost.

The following python modules are needed:

* marathon

## Usage

Among the various `state`s supported by the module, all will require either one of the two
following parameters:

* `app_json`: a path to a file (located on the machine to be managed) that contains
  the JSON application definition for Marathon to manage the app.
* `app`: a JSON-encoded object that describes the application for Marathon to manage.

Consult the Marathon documentation to grok the specification of the JSON objects that
Marathon uses to describe applications.

## Example Playbook

You will need to assign the `marathon-deploy` role to access the `marathon` module

    - hosts: 127.0.0.1
      connection: local
      vars:
        app:
            id: prometheus
            instances: 1
            cpus: 1
            mem: 512
            container:
                type: "DOCKER"
                docker:
                  image: "prom/prometheus:latest"
                  network: "BRIDGE"
                  privileged: false
                  forcePullImage: true
                  portMappings:
                  - containerPort: 9090
                    hostPort: 0
            healthChecks: []
            upgradeStrategy:
                maximumOverCapacity: 0
                minimumHealthCapacity: 0
            labels:
                "MARATHON_SINGLE_INSTANCE_APP": "true"
      roles:
        - marathon-deploy
      tasks:
        - name: run Prometheus on marathon
          marathon: uri=http://marathon-node:8080 app='{{ app | to_json }}' state=present
