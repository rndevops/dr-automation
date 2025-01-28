import os
import json
import time
import boto3
import urllib.request
from datetime import datetime, timezone

# Initialize clients
asg = boto3.client('autoscaling')
route53 = boto3.client('route53')
sns_client = boto3.client('sns')


# Configuration (update lambda environment variables)
CONFIG = {
    'PRIMARY_REGION': os.environ['PRIMARY_REGION'],
    'PRIMARY_ENDPOINT': os.environ['PRIMARY_ENDPOINT'],
    'DR_ENDPOINT': os.environ['DR_ENDPOINT'],
    'DR_ASG_NAME': os.environ['DR_ASG_NAME'],
    'HOSTED_ZONE_ID': os.environ['HOSTED_ZONE_ID'],
    'DOMAIN_NAME': os.environ['DOMAIN_NAME'],
    'SNS_TOPIC_ARN': os.environ['SNS_TOPIC_ARN'],
    'SLACK_WEBHOOK_URL': os.environ['SLACK_WEBHOOK_URL']
}

def lambda_handler(event, context):
    # Step 1: Check primary endpoint
    primary_healthy = check_endpoint(CONFIG['PRIMARY_ENDPOINT'], 10)
    print(CONFIG['PRIMARY_ENDPOINT'])
    print(f"Primary endpoint is healthy: {primary_healthy}")
    
    # If nginx endpoint is not healthy, check DynamoDB endpoint
    # This is to confirm the region is down. Typo (x) is intentional to simulate failure
    if not primary_healthy:
        ddb_healthy = check_endpoint(f'https://dynamodbx.{CONFIG['PRIMARY_REGION']}.amazonaws.com', 1)
    
    # Step 3: Scale up ASG in DR
    if not ddb_healthy:
        update_asg_capacity(2)

    # Step 4: Check DR endpoint. Keep checking every 30 seconds for a maximum of 10 minutes
    dr_healthy = check_endpoint(CONFIG['DR_ENDPOINT'], 10, 30, 20)

    # Step 5: Update DNS once DR is up
    if dr_healthy:
        update_dns_record(CONFIG['DR_ENDPOINT'].replace("https://", ""))
        
    # Capture failover time_stamp
    failover_ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')

    # Step 6: Send email notification
    email_subject = "Application NGINX failed over to DR"
    email_message = f"Application NGINX failed over to DR at {failover_ts}"
    send_email_via_sns(CONFIG['SNS_TOPIC_ARN'], email_subject, email_message)


    # Step 7: Send Slack notification
    slack_message = "Application NGINX failed over to DR at {failover_ts}"
    send_slack_notification(CONFIG['SLACK_WEBHOOK_URL'], slack_message)

def check_endpoint(url, timeout, retry_period=None, max_retries=None):
    retries = 0
    while True:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'DR-Failover-HealthCheck/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.getcode() == 200
        except (urllib.error.URLError, urllib.error.HTTPError):
            pass

        retries += 1
        if max_retries is not None and retries >= max_retries:
            print("Max retries reached. Stopping.")
            return False

        if retry_period is not None:
            time.sleep(retry_period)
        else:
            return False

def update_asg_capacity(min_size):
    try:
        asg.update_auto_scaling_group(
            AutoScalingGroupName=CONFIG['DR_ASG_NAME'],
            MinSize=min_size,
            DesiredCapacity=min_size
        )
    except asg.exceptions.ClientError as e:
        print(f"ASG update error: {str(e)}")

def update_dns_record(target):
    try:
        route53.change_resource_record_sets(
            HostedZoneId=CONFIG['HOSTED_ZONE_ID'],
            ChangeBatch={
                'Changes': [{
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': CONFIG['DOMAIN_NAME'].replace("https://", ""),
                        'Type': 'CNAME',
                        'TTL': 1,
                        'ResourceRecords': [{'Value': target}]
                    }
                }]
            }
        )
    except route53.exceptions.ClientError as e:
        print(f"Route53 update error: {str(e)}")


def send_email_via_sns(topic_arn, subject, message):
    # Publish a message to an SNS topic to send an email.
    try:
        response = sns_client.publish(
            TopicArn=topic_arn,
            Subject=subject,
            Message=message
        )
        print(f"Email sent via SNS successfully: {response}")
    except Exception as e:
        print(f"Failed to send email via SNS: {e}")


def send_slack_notification(webhook_url, message):
    # Send a notification to Slack via webhook.
    try:
        slack_payload = {
            "text": message
        }
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(slack_payload),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        # Send the request and handle the response
        with urllib.request.urlopen(req) as response:
            if response.getcode() == 200:
                print("Slack notification sent successfully.")
            else:
                print(f"Failed to send Slack notification. Response code: {response.getcode()}")
    except Exception as e:
        print(f"Error sending Slack notification: {e}")
