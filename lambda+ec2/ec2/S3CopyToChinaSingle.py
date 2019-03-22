#!/bin/python3.7
import boto3
import os
import time
import datetime
import sys
import json
from urllib.parse import unquote_plus

s3client = boto3.client('s3')
ddb = boto3.client('dynamodb')
cloudwatch = boto3.client('cloudwatch')
event = sys.argv[1]
monitor = '/opt/monitor.txt'
def S3CopyToChinaSingle(event_t):
    event = json.loads(event_t)
    print(event)
    bucket = event['bucket']
    key = unquote_plus(event['key'])
    id = event['id']
    credbucket = event['credbucket']
    credobject = event['credobject']
    dst_bucket = event['dst_bucket']  
    #file_name = '/mnt/tmp/' + key
    file_name = '/mnt/tmp_{}/{}'.format(bucket,key)
    tmp_dir = os.path.dirname(file_name)
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    
    # Read China credential
    print('credbucket = ' + credbucket+'----Key= '+credobject)
    response = s3client.get_object(Bucket=credbucket, Key=credobject)
    ak = response['Body']._raw_stream.readline().decode("UTF8").strip('\r\n')
    sk = response['Body']._raw_stream.readline().decode("UTF8").strip('\r\n')
    print(ak + sk)
    s3CNclient = boto3.client('s3', region_name='cn-north-1',
                              aws_access_key_id=ak,
                              aws_secret_access_key=sk)

    ddb.put_item(TableName='S3Single', 
            Item={
                'id':{'S': id},
                'source_bucket':{'S': bucket},
                'destination_bucket':{'S': dst_bucket},
                'key':{'S': key},
                'complete':{'S': 'N'},
                'start_time':{'N': str(time.time())}
                })
    print('bucket= '+bucket+'----key = '+key+'-----file_name= '+file_name)
    start_time = time.time()
    s3client.download_file(bucket, key, file_name)
    print('Finished download, starting to upload')
    #sys.exit(0)
    s3CNclient.upload_file(file_name, dst_bucket, key)
    end_time = time.time()
    sync_time = end_time - start_time
    #with open(monitor,'a') as f:
    #    f.write("{} {} {} {}\n".format(datetime.datetime.now(), bucket, key, sync_time))
    #    f.close()
    print('Finished uploading take {}s, starting to update table'.format(sync_time))
    ddb.update_item(TableName='S3SingleResult',
        Key={
            "id": {"S": id}
            },
        UpdateExpression="set complete = :c, complete_time = :ctime",
        ExpressionAttributeValues={
            ":c": {"S": "Y"},
            ":ctime": {"N": str(time.time())}
        },
        ReturnValues="UPDATED_NEW" 
    )

    ddb.delete_item(
        TableName='S3Single',
        Key={
            "id": {"S": id}
        }
        )

    if os.path.exists(file_name):
        os.remove(file_name)
        
    try:
        cloudwatch.put_metric_data(
            Namespace='S3Sync',
            MetricData=[
                {
                    'MetricName': 'synctime',
                    'Dimensions': [
                        {
                            'Name': 'Bucket',
                            'Value': bucket
                         },
                    ],
                'Timestamp': time.time(),
                'Value':sync_time,
                'Unit': 'Seconds'
                },
            ])
    except Exception as e:
        print(e)
    print('Copy S3 file '+bucket+'/'+key+ 'to China S3 bucket '+dst_bucket)

S3CopyToChinaSingle(event)
