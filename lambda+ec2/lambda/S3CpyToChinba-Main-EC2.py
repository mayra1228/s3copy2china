import traceback
import boto3
import os
import sys
import time
import math
import json
import hashlib
import random
from urllib.parse import unquote_plus

s3client = boto3.client('s3')
lambdaclient = boto3.client('lambda')
ddb = boto3.client('dynamodb')
ssm = boto3.client('ssm')
ec2 = boto3.client('ec2')
master_id = 'i-0b4591d667f24f095'
slave_id = 'i-022f8aae3643e1a79'
instances_id = ['i-022f8aae3643e1a79','i-0b4591d667f24f095']

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
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = unquote_plus(event['Records'][0]['s3']['object']['key'])
    eventType = event['Records'][0]['eventName']
    dst_bucket = os.environ['DstBucket']
    credbucket = os.environ['CredBucket']
    credobject = os.environ['CredObject']

    # Read China credential
    print('credbucket = ' + credbucket+'----Key= '+credobject)
    response = s3client.get_object(Bucket=credbucket, Key=credobject)
    ak = response['Body']._raw_stream.readline().decode("UTF8").strip('\r\n')
    sk = response['Body']._raw_stream.readline().decode("UTF8").strip('\r\n')
    s3CNclient = boto3.client('s3', region_name='cn-north-1',
                              aws_access_key_id=ak,
                              aws_secret_access_key=sk)
    if not key.endswith('/'):
        try:
            if 'ObjectRemoved' in eventType:
                print('Deleting global S3 object: ' + bucket + '/' + key)
                s3CNclient.delete_object(Bucket=dst_bucket, Key=key)
                print('Deleted China S3 object: ' + dst_bucket + '/' + key)

            if 'ObjectCreated' in eventType:
                head_response = s3client.head_object(Bucket=bucket, Key=key)
                file_length = head_response['ContentLength']
                print('Copying global S3 object: ' + bucket + '/' + key)
                hash_id = hashlib.md5(str([time.time(),bucket,key]).encode('utf-8')).hexdigest()
                ddb.put_item(TableName='S3SingleResult', 
                        Item={
                            'id':{'S': hash_id},
                            'source_bucket':{'S': bucket},
                            'destination_bucket':{'S': dst_bucket},
                            'key':{'S': key},
                            'complete':{'S':'N'}
                            })

                event_str1 = {
                    'bucket' : bucket,
                    'key' : key,
                    'dst_bucket' : dst_bucket,
                    'id' : hash_id,
                    'credbucket' : credbucket,
                    'credobject' : credobject
                }
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
                print('Invoke EC2 function to process single object.')

        except Exception as e:
            print(traceback.format_exc())

    return (bucket, key)