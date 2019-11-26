"""Helper for registering new task definitions on AWS ECS and updating associated services."""

__version__ = "0.1.0"

import argparse
import json
import sys
from typing import Any, Callable, List, Tuple

import boto3


class ECSTask:
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html#ECS.Client.register_task_definition
    task_definition = {}  # type: dict
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html#ECS.Client.update_service
    update_services = []  # type: List[dict]
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html#ECS.Client.run_task
    run_tasks = []  # type: List[dict]
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/events.html#EventBridge.Client.put_targets
    events__put_targets = []  # type: List[dict]
    active_task_count = 5  # type: int

    def boto3_call(self, client, method, **kwargs):
        # type: (str, str, Any) -> dict
        return getattr(boto3.client(client), method)(**kwargs)

    @property
    def family(self):
        # type: () -> str
        return self.task_definition["family"]

    def active_task_definitions(self):
        # type: () -> List[str]
        """List of all active task definition ARNs"""
        return self.boto3_call(
            "ecs",
            "list_task_definitions",
            familyPrefix=self.family,
            status="ACTIVE",
            sort="DESC",
        )["taskDefinitionArns"]

    def ecs_update_services(self, task_definition_arn):
        # type: (str) -> None
        """Update ECS services with latest task definition"""
        for update_service_kwargs in self.update_services:
            self.boto3_call(
                "ecs",
                "update_service",
                taskDefinition=task_definition_arn,
                **update_service_kwargs
            )
            print("  Updated service: {}".format(update_service_kwargs["service"]))

    def ecs_run_tasks(self, task_definition_arn):
        # type: (str) -> None
        """Run any one-off tasks for latest task definition"""
        for run_task_kwargs in self.run_tasks:
            self.boto3_call(
                "ecs", "run_task", taskDefinition=task_definition_arn, **run_task_kwargs
            )
            print("  Running task: {}".format(task_definition_arn.split("/")[1]))

    def put_targets(self, task_definition_arn):
        # type: (str) -> None
        """Update Cloudwatch Event targets with latest task definition"""
        for put_target_kwargs in self.events__put_targets:
            put_target_kwargs["Targets"][0]["EcsParameters"][
                "TaskDefinitionArn"
            ] = task_definition_arn
            self.boto3_call("events", "put_targets", **put_target_kwargs)
            for t in put_target_kwargs["Targets"]:
                print(
                    "  Set '{}' event target: {}".format(
                        put_target_kwargs["Rule"], t["Id"]
                    )
                )

    def deregister_tasks(self):
        """Deregister tasks older than `keep_active` count."""
        for deregister_arn in self.active_task_definitions()[self.active_task_count:]:
            self.boto3_call(
                "ecs", "deregister_task_definition", taskDefinition=deregister_arn
            )
            print("  Deregistered task definition: {}".format(deregister_arn))

    def inject_image_tag(self, image_tag):
        # type: (str) -> None
        """Replace {image_tag} in containerDefinitions[image] with actual image tag"""
        print("Updating tasks to image tag: {}".format(image_tag))
        for container in self.task_definition["containerDefinitions"]:
            container["image"] = container["image"].format(image_tag=image_tag)

    def register_task_definition(self):
        # type: () -> str
        """Register the task definition and return its ARN"""
        arn = self.boto3_call(
            "ecs", "register_task_definition", **self.task_definition
        )["taskDefinition"]["taskDefinitionArn"]
        print("Registered new task definition: {}".format(arn.split("/")[1]))
        return arn

    def deploy(self, image_tag):
        # type: (str) -> None
        """
        Update task definitions with new image_tag, run tasks, update services and event targets,
        finally deregister old task definitions.
        """
        self.inject_image_tag(image_tag)
        arn = self.register_task_definition()
        self.ecs_run_tasks(arn)
        self.ecs_update_services(arn)
        self.put_targets(arn)
        self.deregister_tasks()

    def rollback(self):
        """Rollback services and event targets to previous task definition and deregister current definition"""
        task_defn_arns = self.active_task_definitions()
        self.boto3_call(
            "ecs", "deregister_task_definition", taskDefinition=task_defn_arns[0]
        )
        print(
            "Deregistered latest active task definition: {}".format(
                task_defn_arns[0].split("/")[1]
            )
        )
        arn = task_defn_arns[1]
        print("Rolling back to task definition: {}".format(arn.split("/")[1]))
        self.ecs_update_services(arn)
        self.put_targets(arn)

    def debug(self):
        print(
            json.dumps(
                {
                    k: getattr(self, k)
                    for k in [
                        "task_definition",
                        "update_services",
                        "run_tasks",
                        "events__put_targets",
                    ]
                },
                indent=2,
            )
        )

    def parse_args(self, arg_list):
        # type: (List[str]) -> Tuple[Callable, dict]
        parser = argparse.ArgumentParser(description="ECS Task Update")
        commands = parser.add_subparsers()
        deploy_parser = commands.add_parser(
            "deploy",
            help="Register new task definitions using `image_tag`. "
            "Update defined ECS Services, Event Targets, and run defined ECS Tasks",
        )
        deploy_parser.add_argument(
            "image_tag",
            help="Image tag to use for updating task container definitions.",
        )
        deploy_parser.set_defaults(method=self.deploy)
        rollback_parser = commands.add_parser(
            "rollback",
            help="Deactivate current task definitions and "
            "rollback all ECS Services and Event Targets to previous active definition.",
        )
        rollback_parser.set_defaults(method=self.rollback)
        debug_parser = commands.add_parser(
            "debug", help="Dump JSON generated for class attributes.",
        )
        debug_parser.set_defaults(method=self.debug)
        args = vars(parser.parse_args(arg_list))
        method = args.pop("method")
        return method, args

    def main(self, arg_list=None):
        # type: (List[str]) -> None
        if arg_list is None:
            arg_list = sys.argv[1:]
        method, args = self.parse_args(arg_list)
        method(**args)
