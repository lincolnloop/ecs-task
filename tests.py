import json

import pytest
from ecs_task import ECSTask


def test_parse_deploy_args():
    e = ECSTask()
    method, args = e.parse_args(["deploy", "000"])
    assert method == e.deploy
    assert args == {"image_tag": "000"}


def test_parse_bad_deploy_args():
    e = ECSTask()
    with pytest.raises(SystemExit):
        e.parse_args(["deploy"])


def test_parse_rollback_args():
    e = ECSTask()
    method, args = e.parse_args(["rollback"])
    assert method == e.rollback
    assert args == {}


def test_parse_debug_args():
    e = ECSTask()
    method, args = e.parse_args(["debug"])
    assert method == e.debug
    assert args == {}


def test_parse_bad_rollback_args():
    e = ECSTask()
    with pytest.raises(SystemExit):
        e.parse_args(["rollback", "000"])


def test_main(mocker):
    mocked = mocker.patch.object(ECSTask, "deploy")
    e = ECSTask()
    e.main(["deploy", "000"])
    mocked.assert_called_with(image_tag="000")


def test_family():
    e = ECSTask()
    family = "abc"
    e.task_definition = {"family": family}
    assert e.family == family


def test_service_update(mocker):
    mocked = mocker.patch.object(ECSTask, "boto3_call")
    e = ECSTask()
    e.update_services = [{"service": "b", "c": "d"}, {"service": "2"}]
    e.ecs_update_services("arn")
    assert mocked.call_count == 2
    mocked.assert_has_calls(
        [
            mocker.call(
                "ecs", "update_service", taskDefinition="arn", **e.update_services[0]
            ),
            mocker.call(
                "ecs", "update_service", taskDefinition="arn", **e.update_services[1]
            ),
        ]
    )


def test_run_task(mocker):
    mocked = mocker.patch.object(ECSTask, "boto3_call")
    e = ECSTask()
    e.run_tasks = [{"a": "b"}]
    e.ecs_run_tasks("arn/id")
    assert mocked.call_count == 1
    mocked.assert_called_with(
        "ecs", "run_task", taskDefinition="arn/id", **e.run_tasks[0]
    )


def test_inject_image_tag():
    e = ECSTask()
    e.task_definition = {
        "containerDefinitions": [{"image": "alpine"}, {"image": "my:{image_tag}"}]
    }
    e.inject_image_tag("latest")
    assert e.task_definition["containerDefinitions"] == [
        {"image": "alpine"},
        {"image": "my:latest"},
    ]


def test_active_task_definitions(mocker):
    mocked = mocker.patch.object(ECSTask, "boto3_call")
    e = ECSTask()
    e.task_definition = {"family": "a"}
    e.active_task_definitions()
    mocked.assert_called_with(
        "ecs", "list_task_definitions", familyPrefix="a", status="ACTIVE", sort="DESC"
    )


def test_debug(capsys):
    e = ECSTask()
    e.task_definition = {"family": "a"}
    e.run_tasks = {"cluster": "b"}
    e.debug()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "task_definition": e.task_definition,
        "run_tasks": e.run_tasks,
        "events__put_targets": [],
        "update_services": [],
    }


def test_register_task_definition(mocker):
    mocked = mocker.patch.object(
        ECSTask,
        "boto3_call",
        return_value={"taskDefinition": {"taskDefinitionArn": "arn/id"}},
    )
    e = ECSTask()
    e.task_definition = {"family": "a", "image": "alpine"}
    arn = e.register_task_definition()
    assert arn == "arn/id"
    assert mocked.call_count == 1
    mocked.assert_called_with("ecs", "register_task_definition", **e.task_definition)


def test_events_put_targets(mocker):
    mocked = mocker.patch.object(ECSTask, "boto3_call")
    e = ECSTask()
    e.events__put_targets = [
        {"Rule": "a", "Targets": [{"Id": "lorem", "EcsParameters": {}}]}
    ]
    e.put_targets(task_definition_arn="arn/id")
    assert mocked.call_count == 1
    mocked.assert_called_with(
        "events",
        "put_targets",
        **{
            "Rule": "a",
            "Targets": [
                {"Id": "lorem", "EcsParameters": {"TaskDefinitionArn": "arn/id"}}
            ],
        }
    )


def test_end_to_end(mocker):
    mocked = mocker.patch.object(ECSTask, "boto3_call")
    mocker.patch.object(ECSTask, "register_task_definition", return_value="arn/id")
    mocker.patch.object(
        ECSTask,
        "active_task_definitions",
        return_value=["arn/id:{}".format(i) for i in reversed(range(1, 8))],
    )
    e = ECSTask()
    e.task_definition = {
        "family": "abc",
        "containerDefinitions": [{"image": "my:{image_tag}"}],
    }
    e.update_services = [{"service": "abc"}]
    e.run_tasks = [{"cluster": "lorem"}]
    e.events__put_targets = [
        {"Rule": "a", "Targets": [{"Id": "lorem", "EcsParameters": {}}]}
    ]
    e.main(["deploy", "000"])
    assert mocked.call_count == 5
    mocked.assert_has_calls(
        [
            mocker.call("ecs", "run_task", taskDefinition="arn/id", **e.run_tasks[0]),
            mocker.call(
                "ecs", "update_service", taskDefinition="arn/id", **e.update_services[0]
            ),
            mocker.call(
                "events",
                "put_targets",
                **{
                    "Rule": "a",
                    "Targets": [
                        {
                            "Id": "lorem",
                            "EcsParameters": {"TaskDefinitionArn": "arn/id"},
                        }
                    ],
                }
            ),
            mocker.call("ecs", "deregister_task_definition", taskDefinition="arn/id:2"),
            mocker.call("ecs", "deregister_task_definition", taskDefinition="arn/id:1"),
        ]
    )


def test_end_to_end_rollback(mocker):
    mocked = mocker.patch.object(ECSTask, "boto3_call")
    mocker.patch.object(
        ECSTask,
        "active_task_definitions",
        return_value=["arn/id:{}".format(i) for i in reversed(range(1, 6))],
    )
    e = ECSTask()
    e.task_definition = {
        "family": "abc",
        "containerDefinitions": [{"image": "my:{image_tag}"}],
    }
    e.update_services = [{"service": "abc"}]
    e.run_tasks = [{"cluster": "lorem"}]
    e.events__put_targets = [
        {"Rule": "a", "Targets": [{"Id": "lorem", "EcsParameters": {}}]}
    ]
    e.main(["rollback"])
    assert mocked.call_count == 3
    mocked.assert_has_calls(
        [
            mocker.call("ecs", "deregister_task_definition", taskDefinition="arn/id:5"),
            mocker.call(
                "ecs",
                "update_service",
                taskDefinition="arn/id:4",
                **e.update_services[0]
            ),
            mocker.call(
                "events",
                "put_targets",
                **{
                    "Rule": "a",
                    "Targets": [
                        {
                            "Id": "lorem",
                            "EcsParameters": {"TaskDefinitionArn": "arn/id:4"},
                        }
                    ],
                }
            ),
        ]
    )
