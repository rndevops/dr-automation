import os
import boto3
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration (environment variables)
try:
    CONFIG = {
        "PRIMARY_REGION": os.environ["PRIMARY_AWS_REGION"],
        "DR_REGION": os.environ["DR_AWS_REGION"],
        "PRIMARY_ASG_NAME": os.environ["PRIMARY_ASG_NAME"],
        "DR_ASG_NAME": os.environ["DR_ASG_NAME"],
        "DOMAIN_NAME": os.environ["DOMAIN_NAME"].replace("https://", ""),
        "PRIMARY_DOMAIN_NAME": os.environ["PRIMARY_DOMAIN_NAME"].replace(
            "https://", ""
        ),
        "HOSTED_ZONE_ID": os.environ["HOSTED_ZONE_ID"],
    }
except KeyError as e:
    logger.error(f"Missing environment variable: {e}")
    raise


def lambda_handler(event, context):
    draction = event.get("draction")
    if draction not in ["failover", "failback", "status"]:
        return {
            "statusCode": 400,
            "body": "Invalid draction. Use 'failover', 'failback', or 'status'.",
        }

    primary_region = CONFIG["PRIMARY_REGION"]
    dr_region = CONFIG["DR_REGION"]

    primary_asg = CONFIG["PRIMARY_ASG_NAME"]
    dr_asg = CONFIG["DR_ASG_NAME"]

    return_message = None

    # Create clients for both regions
    primary_client = boto3.client("autoscaling", region_name=primary_region)
    dr_client = boto3.client("autoscaling", region_name=dr_region)

    try:
        if draction == "failover":
            # Scale down primary ASG
            primary_client.set_desired_capacity(
                AutoScalingGroupName=primary_asg, DesiredCapacity=0, HonorCooldown=False
            )
            logger.info(f"Scaled down {primary_asg} in {primary_region}")
            return_message = "Failover triggered successfully."

        elif draction == "failback":
            # Scale up primary ASG
            primary_client.set_desired_capacity(
                AutoScalingGroupName=primary_asg, DesiredCapacity=2, HonorCooldown=False
            )
            logger.info(f"Scaled up {primary_asg} in {primary_region}")

            # Scale down DR ASG
            dr_client.set_desired_capacity(
                AutoScalingGroupName=dr_asg, DesiredCapacity=0, HonorCooldown=False
            )
            logger.info(f"Scaled down {dr_asg} in {dr_region}")

            # Update DNS record to point to primary domain
            update_dns_record()
            return_message = "Failback completed successfully."

        elif draction == "status":
            primary_capacity = get_asg_desired_capacity(primary_client, primary_asg)
            dr_capacity = get_asg_desired_capacity(dr_client, dr_asg)

            if primary_capacity == 0:
                return_message = f"Primary site is down. primary_capacity={primary_capacity}, dr_capacity={dr_capacity}"
            elif dr_capacity == 0:
                return_message = f"Primary site is up. primary_capacity={primary_capacity}, dr_capacity={dr_capacity}"
            else:
                return_message = f"Failover in progress. primary_capacity={primary_capacity}, dr_capacity={dr_capacity}"

    except Exception as e:
        logger.error(f"Error during {draction}: {e}")
        return {"statusCode": 500, "body": f"Error during {draction}: {str(e)}"}

    return {"statusCode": 200, "body": return_message}


def get_asg_desired_capacity(client, asg_name):
    try:
        asg_status = client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg_name]
        )
        desired_capacity = asg_status["AutoScalingGroups"][0]["DesiredCapacity"]
        return desired_capacity
    except client.exceptions.ClientError as e:
        logger.error(f"Error fetching ASG desired capacity for {asg_name}: {e}")
        return None


def update_dns_record(route53_client=None):
    if route53_client is None:
        route53_client = boto3.client("route53")
    # route53 = boto3.client("route53")
    domain_name = CONFIG["DOMAIN_NAME"]
    primary_domain_name = CONFIG["PRIMARY_DOMAIN_NAME"]
    hosted_zone_id = CONFIG["HOSTED_ZONE_ID"]

    try:
        response = route53_client.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": domain_name,
                            "Type": "CNAME",
                            "TTL": 60,
                            "ResourceRecords": [{"Value": primary_domain_name}],
                        },
                    }
                ]
            },
        )
        logger.info(f"DNS updated successfully: {response}")
    except route53.exceptions.ClientError as e:
        logger.error(f"Route53 update error: {e}")
        raise
