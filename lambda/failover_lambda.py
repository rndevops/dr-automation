import os
import json
import time
import boto3
import urllib.request
from datetime import datetime, timezone
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
asg_client = boto3.client("autoscaling")
route53_client = boto3.client("route53")
sns_client = boto3.client("sns")

# Validate environment variables
REQUIRED_ENV_VARS = [
    "PRIMARY_REGION",
    "PRIMARY_ENDPOINT",
    "DR_ENDPOINT",
    "DR_ASG_NAME",
    "HOSTED_ZONE_ID",
    "DOMAIN_NAME",
    "SNS_TOPIC_ARN",
    "SLACK_WEBHOOK_URL",
]
for var in REQUIRED_ENV_VARS:
    if var not in os.environ:
        raise EnvironmentError(f"Missing required environment variable: {var}")

# Configuration
CONFIG = {var: os.environ[var] for var in REQUIRED_ENV_VARS}


def lambda_handler(event, context):
    # Step 1: Check primary endpoint
    primary_healthy = check_endpoint(CONFIG["PRIMARY_ENDPOINT"], 10)
    logger.info(f"Primary endpoint is healthy: {primary_healthy}")

    # If nginx endpoint is not healthy, check DynamoDB endpoint
    # This is to confirm the region is down. Typo (x) is intentional to simulate failure
    ddb_healthy = True
    if not primary_healthy:
        ddb_healthy = check_endpoint(
            f"https://dynamodbx.{CONFIG['PRIMARY_REGION']}.amazonaws.com", 10
        )
        logger.info(f"DynamoDB endpoint is healthy: {ddb_healthy}")

    # Step 3: Scale up ASG in DR
    if not ddb_healthy:
        update_asg_capacity(CONFIG["DR_ASG_NAME"], desired_capacity=2)

    # Step 4: Check DR endpoint. Keep checking every 30 seconds for a maximum of 10 minutes
    dr_healthy = check_endpoint(
        CONFIG["DR_ENDPOINT"], 10, retry_period=30, max_retries=20
    )

    # Step 5: Update DNS once DR is up
    if dr_healthy:
        update_dns_record(CONFIG["DR_ENDPOINT"].replace("https://", ""))
        failover_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
        message = f"Application failed over to DR at {failover_ts}"

        send_notification(
            message=message,
            subject="Application Failover to DR",
            slack_webhook_url=CONFIG["SLACK_WEBHOOK_URL"],
            sns_topic_arn=CONFIG["SNS_TOPIC_ARN"],
        )
    else:
        logger.error("Failover failed: DR endpoint is not healthy")


def check_endpoint(url, timeout, retry_period=None, max_retries=None):
    retries = 0
    while True:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "DR-Failover-HealthCheck/1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.getcode() == 200
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logger.warning(f"Error checking endpoint {url}: {e}")

        retries += 1
        if max_retries is not None and retries >= max_retries:
            logger.error("Max retries reached for endpoint check.")
            return False

        if retry_period:
            time.sleep(retry_period)
        else:
            return False


def update_asg_capacity(asg_name, desired_capacity, asg_client=None):
    if asg_client is None:
        asg_client = boto3.client("autoscaling")

    try:
        asg_client.update_auto_scaling_group(
            AutoScalingGroupName=asg_name,
            DesiredCapacity=desired_capacity,
        )
        logger.info(
            f"Updated ASG {asg_name} to DesiredCapacity={desired_capacity}"
        )
    except Exception as e:
        logger.error(f"Error updating ASG {asg_name}: {e}")


def update_dns_record(target, route53_client=None):
    if route53_client is None:
        route53_client = boto3.client("route53")

    try:
        route53_client.change_resource_record_sets(
            HostedZoneId=CONFIG["HOSTED_ZONE_ID"],
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": CONFIG["DOMAIN_NAME"].replace("https://", ""),
                            "Type": "CNAME",
                            "TTL": 30,
                            "ResourceRecords": [{"Value": target}],
                        },
                    }
                ]
            },
        )
        logger.info(f"Updated DNS record to point to {target}")
    except Exception as e:
        logger.error(f"Error updating DNS record: {e}")


def send_notification(
    message, subject=None, slack_webhook_url=None, sns_topic_arn=None
):
    if slack_webhook_url:
        send_slack_notification(slack_webhook_url, message)

    if sns_topic_arn:
        send_email_via_sns(sns_topic_arn, subject or "Notification", message)


def send_email_via_sns(topic_arn, subject, message, sns_client=None):
    if sns_client is None:
        sns_client = boto3.client("sns")

    try:
        response = sns_client.publish(
            TopicArn=topic_arn, Subject=subject, Message=message
        )
        logger.info(f"Email sent via SNS successfully: {response}")
    except Exception as e:
        logger.error(f"Failed to send email via SNS: {e}")


def send_slack_notification(webhook_url, message):
    try:
        slack_payload = {"text": message}
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(slack_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as response:
            if response.getcode() == 200:
                logger.info("Slack notification sent successfully.")
            else:
                logger.error(
                    f"Failed to send Slack notification. Response code: {response.getcode()}"
                )
    except Exception as e:
        logger.error(f"Error sending Slack notification: {e}")
