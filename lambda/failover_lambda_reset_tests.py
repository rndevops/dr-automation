import os
import pytest
from unittest import mock
from failover_lambda_reset import lambda_handler, get_asg_desired_capacity, update_dns_record

# Set up required environment variables for testing
os.environ["PRIMARY_AWS_REGION"] = "us-west-2"
os.environ["DR_AWS_REGION"] = "us-east-1"
os.environ["PRIMARY_ASG_NAME"] = "primary-asg"
os.environ["DR_ASG_NAME"] = "dr-asg"
os.environ["DOMAIN_NAME"] = "rndevops.site"
os.environ["PRIMARY_DOMAIN_NAME"] = "primary.rndevops.site"
os.environ["HOSTED_ZONE_ID"] = "Z1234567890"


@mock.patch("boto3.client")
def test_lambda_handler_failover(mock_boto_client):
    # Mock AWS services
    mock_primary_client = mock.Mock()
    mock_dr_client = mock.Mock()
    mock_boto_client.side_effect = [mock_primary_client, mock_dr_client]

    event = {"draction": "failover"}
    context = {}

    with mock.patch("failover_lambda_reset.update_dns_record") as mock_update_dns_record:
        response = lambda_handler(event, context)

        # Ensure the ASG capacities were set
        mock_primary_client.set_desired_capacity.assert_called_once_with(
            AutoScalingGroupName="primary-asg", DesiredCapacity=0, HonorCooldown=False
        )
        assert response["statusCode"] == 200
        assert response["body"] == "Failover triggered successfully."
        mock_update_dns_record.assert_not_called()


@mock.patch("boto3.client")
def test_lambda_handler_failback(mock_boto_client):
    # Mock AWS services
    mock_primary_client = mock.Mock()
    mock_dr_client = mock.Mock()
    mock_boto_client.side_effect = [mock_primary_client, mock_dr_client]

    event = {"draction": "failback"}
    context = {}

    with mock.patch("failover_lambda_reset.update_dns_record") as mock_update_dns_record:
        response = lambda_handler(event, context)

        # Ensure the ASG capacities were set
        mock_primary_client.set_desired_capacity.assert_called_once_with(
            AutoScalingGroupName="primary-asg", DesiredCapacity=2, HonorCooldown=False
        )
        mock_dr_client.set_desired_capacity.assert_called_once_with(
            AutoScalingGroupName="dr-asg", DesiredCapacity=0, HonorCooldown=False
        )
        assert response["statusCode"] == 200
        assert response["body"] == "Failback completed successfully."
        mock_update_dns_record.assert_called_once()


@mock.patch("boto3.client")
def test_lambda_handler_status(mock_boto_client):
    # Mock AWS services
    mock_primary_client = mock.Mock()
    mock_dr_client = mock.Mock()
    mock_boto_client.side_effect = [mock_primary_client, mock_dr_client]

    # Mock desired capacities
    mock_primary_client.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [{"DesiredCapacity": 0}]
    }
    mock_dr_client.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [{"DesiredCapacity": 2}]
    }

    event = {"draction": "status"}
    context = {}

    response = lambda_handler(event, context)

    assert response["statusCode"] == 200
    assert "Primary site is down" in response["body"]


def test_get_asg_desired_capacity():
    mock_client = mock.Mock()
    mock_client.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [{"DesiredCapacity": 2}]
    }

    capacity = get_asg_desired_capacity(mock_client, "test-asg")
    assert capacity == 2
    mock_client.describe_auto_scaling_groups.assert_called_once_with(
        AutoScalingGroupNames=["test-asg"]
    )


@mock.patch("boto3.client")
def test_update_dns_record(mock_boto_client):
    mock_route53_client = mock.Mock()
    mock_boto_client.return_value = mock_route53_client

    update_dns_record()
    mock_route53_client.change_resource_record_sets.assert_called_once_with(
        HostedZoneId="Z1234567890",
        ChangeBatch={
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": "rndevops.site",
                        "Type": "CNAME",
                        "TTL": 60,
                        "ResourceRecords": [{"Value": "primary.rndevops.site"}],
                    },
                }
            ]
        },
    )
