import os
import json
import boto3

def lambda_handler(event, context):
    draction = event['draction']
    
    primary_region = os.environ['PRIMARY_AWS_REGION']
    dr_region = os.environ['DR_AWS_REGION']
    
    primary_asg = os.environ['PRIMARY_ASG_NAME']
    dr_asg = os.environ['DR_ASG_NAME']

    return_message = None
    
    # Create clients for both regions
    primary_client = boto3.client('autoscaling', region_name=primary_region)
    dr_client = boto3.client('autoscaling', region_name=dr_region)
    
    # Failover
    if draction == 'failover':
        scale_up_response = dr_client.set_desired_capacity(
            AutoScalingGroupName=dr_asg,
            DesiredCapacity=2,
            HonorCooldown=False
        )
        print(f"Scaled up {dr_asg} in {dr_region}: {scale_up_response}")
    
        scale_down_response = primary_client.set_desired_capacity(
            AutoScalingGroupName=primary_asg,
            DesiredCapacity=0,
            HonorCooldown=False
        )
        print(f"Scaled down {primary_asg} in {primary_region}: {scale_down_response}")
        return_message = "Failover completed successfully."
    # Failback
    elif draction == 'failback':    
        scale_up_response = primary_client.set_desired_capacity(
            AutoScalingGroupName=primary_asg,
            DesiredCapacity=2,
            HonorCooldown=False
        )
        print(f"Scaled up {primary_asg} in {primary_region}: {scale_up_response}")

        scale_down_response = dr_client.set_desired_capacity(
            AutoScalingGroupName=dr_asg,
            DesiredCapacity=0,
            HonorCooldown=False
        )
        print(f"Scaled down {dr_asg} in {dr_region}: {scale_down_response}")

        # Update DNS record to point to primary DNS
        update_dns_record()

        return_message = "Failback completed successfully."
    # Status
    elif draction == 'status':
        primary_asg_status = primary_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[primary_asg]
        )
        primary_desired_capacity = primary_asg_status['AutoScalingGroups'][0]['DesiredCapacity']

        print(f"Primary_desired_capacity: {primary_desired_capacity}")

        dr_asg_status = dr_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[dr_asg]
        )
        dr_desired_capacity = dr_asg_status['AutoScalingGroups'][0]['DesiredCapacity']

        print(f"Primary_desired_capacity: {primary_desired_capacity}")
        if primary_desired_capacity == 0:
            return_message = f"Primary site is down. primary_desired_capacity = {primary_desired_capacity}, dr_desired_capacity = {dr_desired_capacity}"
        elif dr_desired_capacity == 0:
            return_message = f"DR site is down. primary_desired_capacity = {primary_desired_capacity}, dr_desired_capacity = {dr_desired_capacity}"
        else:
            return_message = f"Failover is in progress. primary_desired_capacity = {primary_desired_capacity}, dr_desired_capacity = {dr_desired_capacity}"
    else:
        return_message = "Invalid draction. Please use 'failover', 'failback', or 'status'. Usage:  https://drtest.rndevops.site/?draction=status"
    
    return {
        'statusCode': 200,
        'body': return_message
    }

def update_dns_record():
    route53 = boto3.client('route53')
    domain_name = os.environ['DOMAIN_NAME'].replace("https://", "")
    primary_domain_name = os.environ['PRIMARY_DOMAIN_NAME'].replace("https://", "")
    hosted_zone_id = os.environ['HOSTED_ZONE_ID']
    try:
        route53.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch={
                'Changes': [{
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': domain_name,
                        'Type': 'CNAME',
                        'TTL': 1,
                        'ResourceRecords': [{'Value': primary_domain_name}]
                    }
                }]
            }
        )
    except route53.exceptions.ClientError as e:
        print(f"Route53 update error: {str(e)}")
