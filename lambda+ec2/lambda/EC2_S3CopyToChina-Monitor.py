import boto3
import json
import time
import random
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

ssm = boto3.client('ssm')

def health_check():
    response = ssm.describe_instance_information(
        Filters=[
            {
                'Key': 'tag:Role',
                'Values': ['s3sync']
            },
        ]
        )['InstanceInformationList']
    check = [ ec2['InstanceId'] for ec2 in response ]
    ec2_id = random.choice(check)
    return ec2_id
    
def lambda_handler(event, context):
    ec2_id = health_check()
    print("The instance id of running task is {}".format(ec2_id))
    ddb = boto3.resource('dynamodb')
    # Monitor S3 single object task.
    now_time = time.time()
    table = ddb.Table('S3Single')
    s_response = table.scan(
        FilterExpression=Attr('complete').eq('N') & Attr('complete_time').lt(Decimal(now_time)-300)
        )
    print(s_response)
    j = 0
    for m in s_response['Items']:
        s_info = s_response['Items'][j]
        s_bucket = s_info['source_bucket']
        s_key = s_info['key']
        dst_bucket = s_info['destination_bucket']
        id = s_info['id']

        event_str = {
            'bucket' : s_bucket,
            'key' : s_key,
            'dst_bucket' : dst_bucket,
            'id' : id,
            'credbucket' : credbucket,
            'credobject' : credobject
        }
        # payload_json = json.dumps(event_str)
        # print(payload_json)
        payload_str = str(event_str1).replace("\'","\"")
        response = ssm.send_command(
            InstanceIds=[ec2_id, ],
            DocumentName='AWS-RunShellScript',
            TimeoutSeconds=600,
            Comment='string',
            Parameters={ 'commands': ['python3.7 /opt/scripts/S3CopyToChinaSingle.py \'{paras}\''.format(paras=payload_str)]},
            MaxConcurrency='5',
            MaxErrors='5'
        )
        j += 1
    print('Invoke '+str(j)+' Lambda to restart timeout tasks for single object.')
