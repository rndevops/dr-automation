# DR Automation
Solution for automatic failover to DR environment

# Infra setup:

### Components:
- Route53 Hosted Zone
- Public certificate from ACM
- Application Load Balancers
- EC2 Instances
- Auto Scaling Groups
- Node Role, Launch Template and Instance Profile
- Lambda Execution Role
- EC2 and ALB Security Groups
- API Gateway (APIs and Custom Domain)
- Event Bridge Rule

This is a simple NGINX webserver running in an autoscaling group, behind an application load balancer. In primary region two instances are active, and in DR region no instances are active.

### Two lambda functions are setup to test the automation

**DR_FAIL_OVER lambda function:** This is used to check the status, trigger the failover or failback. Invoked via API Gateway endpoints (can use curl).

### Usage: 
##### Check the status: https://drtest.<website_name>/?draction=status
	Shows which site is up currently, with the number of instances in ASG
##### Trigger failover: https://drtest.<website_name>/?draction=failover
	Sets the primary region ASG desired capacity to zero
##### Trigger failback: https://drtest.<website_name>/?draction=failback
	Sets the primary region ASG desired capacity to two, DR region capacity to zero, and points the main DNS to primary endpoint


**DR_FAIL_OVER_AUTOMATION lambda function:** This is invoked every 5 minutes (configurable) via Event Bridge. If primary endpoint is down, it checks DynamoDB endpoint to confirm if the region is down. Then scales up the DR ASG, and switches the DNS.

### To test:
1. Check the status: curl https://drtest.<website_name>/?draction=status
2. Verify the site
	- https://<main_website_name>
	- https://<primary_website_name>
	- https://<dr_website_name>
3. Scale down the primary ASG. curl https://drtest.<website_name>/?draction=failover
4. Keep checking the website status with the URLs in step #2
5. Failover should complete automatically in 5 to 10 minutes
6. Optional: To failback, https://drtest.<website_name>/?draction=failback
