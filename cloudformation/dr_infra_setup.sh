aws cloudformation create-stack \
  --stack-name WebStack \
  --template-body file://nginx_setup_cfn.yml \
  --parameters \
    ParameterKey=VpcId,ParameterValue=vpc-1234567890 \
    ParameterKey=SubnetIds,ParameterValue="subnet-abcdefgh,subnet-ijklmnop" \
    ParameterKey=DomainName,ParameterValue=primary.sample.com \
    ParameterKey=HostedZoneId,ParameterValue=KQ4CHPU0PV2Y \
    ParameterKey=MinSize,ParameterValue=0 \
    ParameterKey=MaxSize,ParameterValue=2 \
    ParameterKey=DesiredSize,ParameterValue=2 \
  --region us-east-1
