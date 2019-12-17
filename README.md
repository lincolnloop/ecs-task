# `ecs-task`

`ecs-task` is an opinionated, but flexible tool for deploying to [Amazon Web Service's Elastic Container Service](https://aws.amazon.com/ecs/).

It is built on the following premises:

* ECS Services, load balancers, auto-scaling, etc. are managed elsewhere, e.g. Terraform, Cloudformation, etc.
* Deploying to ECS is defined as:
    1. Update task definition with new image tag
    2. [Optional] Running any number of one-off Tasks, e.g. Django database migrations.
    3. [Optional] Updating Services to use the new Task Definition.
    4. [Optional] Updating Cloudwatch Event Targets to use the new Task Definition.
    5. Deregister old Task Definitions.
* Applications manage their own Task/Container definitions and can deploy themselves to a pre-defined ECS Cluster.
* The ability to rollback is important and should be as easy as possible.

# Installation

```
pip install ecs-task
``` 

(Optionally, just copy `ecs_task.py` to your project and install `boto3`).

# Usage

This module is made up of a single class, `ecs_task.ECSTask` which is designed to be extended in your project. A basic example:

```python
#!/usr/bin/env python
from ecs_task import ECSTask

class WebTask(ECSTask):
    task_definition = {
        "family": "web",
        "executionRoleArn": EXECUTION_ROLE_ARN,
        "containerDefinitions": [
            {
                "name": "web",
                "image": "my_image:{image_tag}",
                "portMappings": [{"containerPort": 8080}],
                "cpu": 1024,
                "memory": 1024,
            }
        ],
    }
    update_services = [{"service": "web", "cluster": "my_cluster",}]

if __name__ == "__main__":
    WebTask().main()
```

You could save this as `_ecs/web_dev.py` and then execute it with `python -m _ecs.web_dev --help`

```
usage: web_dev.py [-h] {deploy,rollback,debug} ...

ECS Task

positional arguments:
  {deploy,rollback,debug}
    deploy              Register new task definitions using `image_tag`.
                        Update defined ECS Services, Event Targets, and run
                        defined ECS Tasks
    rollback            Deactivate current task definitions and rollback all
                        ECS Services and Event Targets to previous active
                        definition.
    debug               Dump JSON generated for class attributes.

optional arguments:
  -h, --help            show this help message and exit
```

## Class attributes

A sub-class of `ECSTask` must include a `task_definition` to do anything. Any other attributes are optional. The following attributes are designed to be a 1-to-1 mapping to an AWS API endpoint via [`boto3`](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html). The values you provide will be passed as keyword arguments to the associated method with the correct Task Definition inserted. Any attribute that takes a list can make multiple calls to the given API.

* `task_definition`: (dict) [`ecs.register_task_definition` docs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html#ECS.Client.register_task_definition)
* `update_services` (list) [`ecs.update_service` docs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html#ECS.Client.update_service)
* `run_tasks` (list) [`ecs.run_task` docs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html#ECS.Client.run_task)
* `events__put_targets` (list) [`events.put_targets` docs](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/events.html#EventBridge.Client.put_targets)

A few additional attributes are available:

* `active_task_count`: (int) the number of task definitions to keep active after a deployment. Default is `10`.
* `sns_notification_topic_arn`: (str) the ARN for an SNS topic which will receive a message whenever an AWS API call is executed. This can be used to trigger notifications or perform additional tasks related to the deployment. The message is in the format:

    ```python
      {
        "client": client,  # boto3 client (usually "ecs")
        "method": method,  # method called (e.g., "update_service")
        "input": kwargs,   # method input as a dictionary
        "result": result   # results from AWS API
      }
    ```
* `notification_method_blacklist_regex` (re.Pattern) a pattern of methods to avoid sending notifications for. Default is `re.compile(r"^describe_|get_|list_|.*register_task")`

## Command Interface

Each class is intended to be "executable" by calling `.main()`. Multiple class instances can be called in a given file by using:

```python
if __name__ == "__main__":
    for klass in [WebTask, WorkerTask]:
        klass().main()
```

### `debug`

Just prints the value of each class attribute to the console. Useful if you're doing some class inheritance and want to verify what you have before running against AWS. 

### `deploy`

The `deploy` subcommand accepts an additional argument, `image_tag` which is used to update any Container Definitions in the task which have the `{image_tag}` placeholder. It will:

1. Register a new Task Definition
2. Run Tasks (as defined in `run_tasks`)
3. Update Services (as defined in `update_services`)
4. Update Event Targets (as defined in `events__put_targets`)
5. Deregister any active Task Definitions older than `active_task_count` (by default, `10`)

### `rollback`

1. Deregister the latest active Task Definition
2. Update Services (as defined in `update_services`) with the previous active Task Definition
3. Update Event Targets (as defined in `events__put_targets`) with the previous active Task Definition