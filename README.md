# Ansible Role: marathon-deploy

An Ansible role that helps deploying applications on marathon.

The core of the role is a module to support an operation like

    - name: run application on marathon
      marathon: uri=http://marathon-node:8080 app_json='nginx.json' state=present

## Requirements

The module shipping with the role is supposed to run on a node that can send
REST requests to the marathon endpoint. Typically this could be the localhost.

The following python modules are needed:

* marathon

## Example Playbook

You will need to assign the marathon-deploy role to access the marathon module

    - hosts: 127.0.0.1
      connection: local
      roles:
        - marathon-deploy

      tasks:
        - name: run application on marathon
          marathon: uri=http://marathon-node:8080 app_json='nginx.json' state=present
