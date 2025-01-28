from datetime import datetime, timezone
import os
import json
import pytest
from unittest import mock
from failover_lambda import (
    lambda_handler,
    check_endpoint,
    update_asg_capacity,
    update_dns_record,
    send_email_via_sns,
    send_slack_notification,
)

# Set up required environment variables for testing
os.environ["PRIMARY_REGION"] = "us-west-2"
os.environ["PRIMARY_ENDPOINT"] = "https://primary.rndevops.site"
os.environ["DR_ENDPOINT"] = "https://dr.rndevops.site"
os.environ["DR_ASG_NAME"] = "dr-asg"
os.environ["HOSTED_ZONE_ID"] = "Z123456789"
os.environ["DOMAIN_NAME"] = "rndevops.site"
os.environ["SNS_TOPIC_ARN"] = "arn:aws:sns:us-east-1:123456789012:MyTopic"
os.environ["SLACK_WEBHOOK_URL"] = (
    "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
)


@mock.patch("failover_lambda.boto3.client")
def test_lambda_handler(mock_boto_client):
    mock_asg_client = mock.Mock()
    mock_route53_client = mock.Mock()
    mock_sns_client = mock.Mock()
    mock_boto_client.side_effect = [
        mock_asg_client,
        mock_route53_client,
        mock_sns_client,
    ]

    event = {"key1": "value1"}
    context = {}

    with mock.patch(
        "failover_lambda.check_endpoint", side_effect=[False, False, True]
    ), mock.patch("failover_lambda.datetime") as mock_datetime, mock.patch(
        "failover_lambda.send_notification"
    ) as mock_send_notification:

        mock_datetime.now.return_value = datetime(
            2025, 1, 28, 9, 59, 0, tzinfo=timezone.utc
        )
        lambda_handler(event, context)

        mock_send_notification.assert_called_once()


def test_check_endpoint():
    with mock.patch("failover_lambda.urllib.request.urlopen") as mock_urlopen:
        mock_response = mock.Mock()
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        assert check_endpoint("https://rndevops.site", 10) == True


@mock.patch("failover_lambda.boto3.client")
def test_send_email_via_sns(mock_boto_client):
    mock_sns_client = mock.Mock()
    mock_boto_client.return_value = mock_sns_client

    send_email_via_sns(
        "arn:aws:sns:us-east-1:123456789012:MyTopic", "Test Subject", "Test Message"
    )
    mock_sns_client.publish.assert_called_once_with(
        TopicArn="arn:aws:sns:us-east-1:123456789012:MyTopic",
        Subject="Test Subject",
        Message="Test Message",
    )


def test_send_slack_notification():
    with mock.patch("failover_lambda.urllib.request.urlopen") as mock_urlopen:
        mock_response = mock.Mock()
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value = mock_response

        send_slack_notification(
            "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX",
            "Test Message",
        )
        mock_urlopen.assert_called_once_with(mock.ANY)


@mock.patch("boto3.client")
def test_update_asg_capacity(mock_boto_client):
    mock_asg_client = mock.Mock()
    mock_boto_client.return_value = mock_asg_client

    mock_asg_client.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {
                "AutoScalingGroupName": "dr-asg",
                "MinSize": 1,
                "MaxSize": 10,
                "DesiredCapacity": 1,
                "Instances": [],
            }
        ]
    }

    update_asg_capacity("dr-asg", desired_capacity=2)

    mock_asg_client.update_auto_scaling_group.assert_called_once_with(
        AutoScalingGroupName="dr-asg", DesiredCapacity=2
    )


@mock.patch("boto3.client")
def test_update_dns_record(mock_boto_client):
    mock_route53_client = mock.Mock()
    mock_boto_client.return_value = mock_route53_client

    mock_route53_client.change_resource_record_sets.return_value = {
        "ChangeInfo": {
            "Id": "/change/C2682N5HXP0BZ4",
            "Status": "PENDING",
            "SubmittedAt": "2025-01-28T09:59:00Z",
        }
    }

    update_dns_record("new.target.com")

    mock_route53_client.change_resource_record_sets.assert_called_once_with(
        HostedZoneId="Z1234567890",
        ChangeBatch={
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": "rndevops.site",
                        "Type": "CNAME",
                        "TTL": 30,
                        "ResourceRecords": [{"Value": "new.target.com"}],
                    },
                }
            ]
        },
    )
