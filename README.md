Globa S3同步China S3最终方案

> 参考文档
>
> https://aws.amazon.com/cn/blogs/china/lambda-overseas-china-s3-file/

### 1 架构图

![S3同步](/Users/zhaoxuemei/Documents/项目/三星/S3同步/S3同步.png)

### 2 逻辑实现
在source S3配置events，有任何create/delete object的动作会触发Lambda Main函数，Lambda函数会测试EC2实例的健康状态，将请求通过ssm发送到Active server。请求格式类似如下格式：

```
python3.7 S3CopyToChina.py '{"bucket": "s3-virginia-to-china-speed-bespin", "key": "test.img", "dst_bucket": "develop-s3-beijing-bespin-test", "id": "6f7d463b28c08d330d2424b65f2d32d4", "credbucket": "s3-virginia-to-china-speed3", "credobject": "S3Beijingcredential.txt"}'
```
EC2上的 S3CopyToChinaSingle.py脚本负责同步脚本，完成同步后更新dynamoDB的S3SingleResult表并删除S3Single表中的该条目。更新数据库之后将同步时间上传的到dyanmoDB，最后删除服务器上的临时文件。
### 3 功能模块

### 4 部署步骤

#### 1 创建角色s3syncrole并附加到EC2实例

实例权限如下：

- 
  AmazonEC2RoleforSSM
- AmazonS3FullAccess
- AmazonDynamoDBFullAccess
- AmazonSSMFullAccess

#### 2 实例配置BBR

> BBR: Bottleneck Bandwidth and RTT,就是瓶颈带宽和往返时延的缩写，是一种新型的TCP传输拥塞控制算法。可利用该算法更有效的利用网络带宽，提高传输效率和降低网络延时。linux的4.09内核后都采用了此算法，如下为开启方法。

```shell
# uname -r //查看当前的内核版本
# 如果内核版本不够需要升级内核
# vim /etc/sysctl.conf
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
# sysctl -p
sysctl net.ipv4.tcp_available_congestion_control
# lsmod | grep bbr
  tcp_bbr                16384  3
```

#### 3 安装python3.6及boto3等模块

#### 3 部署脚本

```shell
# mkdir /opt/scripts/
# git clone https://github.com/mayra1228/s3copy2china/blob/master/lambda%2Bec2/ec2/S3CopyToChinaSingle.py
# chmod a+x S3CopyToChinaSingle.py
```

#### 4 DynamoDB表的创建

> 创建2个 DynamodDB 表：
>
> S3Single ：小于5MB文件不分段，记录单个文件的任务信息，在任务完成后删除数据。
>
> S3SingleResult ：所有单个文件任务的信息，一直保存。

表1

Table name:  S3Single

Primary partition key: id (String)

表2

Table name:  S3SingleResult

Primary partition key: id (String)

#### 5 创建lambda执行角色并配置Lambda Main函数

5.1 将中国区放在global的S3中，并设置只允许lambda函数读取

```
# vim S3BJScredential.txt //第一行为 Access key ，第二行为 Secret Key
****************GPLQ
****************qrCc
# aws s3 copy S3BJScredential.txt s3://sourcebucket/
# 在控制台编辑policy，只允许 Lambda 服务访问，其他用户不能下载
{
"Version": "2012-10-17",
"Id": "AllowOnlyLambda",
"Statement": [
{
"Sid": "AllowOnlyLambda",
"Effect": "Deny",
"NotPrincipal": {
"Service": "lambda.amazonaws.com"
},
"Action": "S3:GetObject",
"Resource": "arn:aws:S3:::globalbucket/S3BJScredential.txt"
}
]
}
```

5.2 创建 Lambda 主函数

> Name:  S3CopyToChina-Main，Runtime: Python 3.6，Role :  Lambda-S3copy

1） 配置超时 Timeout=5 mins
2） 环境变量设置
CredBucket = < 海外区域存放 credential  S3  bucket>
CredObject = < 海外区域存放 credential  S3  object>
DstBucket = < 中国目标  S3  bucket>
3）编辑主函数
```
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
master_id = ''
slave_id = ''
instances_id = ['','']

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
```
4) (可选)开启DLQ资源

#### 6 创建监控函数，配置cloudwatch events，每隔5分钟触发一次

函数部分：https://github.com/mayra1228/s3copy2china/blob/master/lambda%2Bec2/lambda/EC2_S3CopyToChina-Monitor.py
#### 7 源S3 Bucket中events的创建

#### 8 测试
```
# aws s3 ls --recursive s3://SOURCE_BUCKET_NAME --summarize > bucket-contents-source.txt 
# aws s3 ls --recursive s3://NEW_BUCKET_NAME --summarize > bucket-contents-new.txt
```