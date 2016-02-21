import operator
import click
import datetime
import boto3
import arrow
import json
import beekeeper
import base64
import os
import urllib2
import glob

class AWS(beekeeper.Beekeeper):
    """Class to handle AWS API calls. Inherits from beekeeper.Beekeeper class"""

    def __init__(self, profile='default'):
        super(AWS, self).__init__(profile)

        # Instantiate an AWS session
        self.boto3 = boto3.Session(
            aws_access_key_id = self.aws_access_key_id,
            aws_secret_access_key = self.aws_secret_access_key,
            region_name = self.aws_region
        )

    def get_instance(self):
        """Get basic instance info

        Returns:
            dict: instance attributes
        """

        # Check if this method was already run within the same command input. If so, get the instance status from self
        if self.instance:
            return self.instance

        try:
            client = self.boto3.client('ec2')
            response = client.describe_instances(InstanceIds=[self.aws_instance_id])
            if response['Reservations'][0]['Instances'][0]:
                results = self.parse_instance_result(response['Reservations'][0]['Instances'][0])

                # Get the volume size and add it to the result
                volume = self.get_volume()
                if volume:
                    results['volume_size'] = volume['Volumes'][0]['Size']

                # Cache the status result in self in case this method is called again from within the same command input
                self.instance = results
                return results
            else:
                return None
        except Exception as e:
            self.log_error(e)

    def list_instances(self, region):
        """List all instances in a region

        Args:
            region (str): An AWS region code

        Returns:
            list: of instance dictionary objects
        """
        try:
            client = self.boto3.client('ec2', region_name=region)
            response = client.describe_instances()
            results = []
            for reservation in response['Reservations']:
                result = self.parse_instance_result( reservation['Instances'][0])
                results.append(result)
            return results
        except Exception as e:
            self.log_error(e)

    def start_instance(self):
        """Start an instance"""
        try:
            client = self.boto3.client('ec2')
            response = client.start_instances(
                InstanceIds=[self.aws_instance_id]
            )
            return response

        except Exception as e:
            self.log_error(e)


    def stop_instance(self):
        """Stop an instance"""
        # TODO Make sure no tests are running before stopping an instance
        try:
            client = self.boto3.client('ec2')
            response = client.stop_instances(
                InstanceIds=[self.aws_instance_id]
            )
            return response

        except Exception as e:
            self.log_error(e)

    def get_snapshot(self):
        """Get the most current AMI image

        Returns:
            dict: snapshot attributes
        """

        client = self.boto3.client('ec2')
        response = client.describe_images(
            Filters=[{'Name': 'tag:beekeeper_instance_id', 'Values': [self.aws_instance_id]}])

        if not response['Images']:
            return None

        # Sort the list of images created for the instance
        unsorted = {}
        for image in response['Images']:
            creation_date = image['CreationDate']
            unsorted[creation_date] = image
        sorted_images = sorted(unsorted.items(), key=operator.itemgetter(0), reverse=True)

        # Return the first array element i.e. the most current image
        current_image = sorted_images[0][1]
        result = {
            'image_id': current_image['ImageId'],
            'snapshot_id': current_image['BlockDeviceMappings'][0]['Ebs']['SnapshotId'],
            'created_datestring': current_image['CreationDate'],
            'created_humanize': arrow.get(current_image['CreationDate']).humanize(),
            'state': current_image['State']
        }
        return result

    def get_task_queue(self, image_id):
        """Get current task queue"""
        try:
            client = boto3.client('sqs')

            # Get queue URL
            queue_name = "beeworker_task_" + image_id
            response = client.get_queue_url(
                QueueName = queue_name,
            )
            queue_url = response['QueueUrl']

            # Get attributes of this queue
            response = client.get_queue_attributes(
                QueueUrl = queue_url,
                AttributeNames = ['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
            )

            result = {
                'queue_name': queue_name,
                'queue_url': queue_url,
                'message_count' : response['Attributes']['ApproximateNumberOfMessages'],
                'message_in_process' : response['Attributes']['ApproximateNumberOfMessagesNotVisible']
            }

            return result

        except Exception as e:
            self.log_error(e)

    def parse_instance_result(self, instance):
        """Helper function to parses the AWS describe_instance() response into a simplier structure for beekeeper purposes"""

        # Notes:
        # volume_id requires validation since terminated instances do not have a volume
        # subnet_id require validation since only instances within a VPC will have a subnet id
        result = {
            'instance_id': instance['InstanceId'],
            'name': self.get_tag_value(instance['Tags'], 'Name'),
            'instance_type': instance['InstanceType'],
            'state': instance['State']['Name'],
            'availability_zone': instance['Placement']['AvailabilityZone'],
            'volume_id': instance['BlockDeviceMappings'][0]['Ebs']['VolumeId'] if instance['BlockDeviceMappings'] else None,
            'key_name': instance['KeyName'],
            'security_group_id': instance['SecurityGroups'][0]['GroupId'],
            'subnet_id': instance['SubnetId'] if hasattr(instance, 'SubnetId') else ''
        }
        return result

    def create_snapshot(self):
        """Create an AMI image of an instance"""
        try:
            # Create AMI image
            client = self.boto3.client('ec2')
            image = client.create_image(
                InstanceId = self.aws_instance_id,
                Name = 'Beekeeper ' + self.timestamp("%Y%m%d%H%M%S"),   # returns a timestamp suitable as an image name i.e. no hyphens
                Description = 'AMI image created by Beekeeper on ' + self.timestamp(),
                NoReboot = True
            )

            # Set a tag to identify which instance the image belong to
            response = client.create_tags(
                Resources=[image['ImageId']],
                Tags = [{'Key': 'beekeeper_instance_id', 'Value': self.aws_instance_id}])

            # Wait for image to be ready before returning
            waiter = client.get_waiter('image_available')
            waiter.wait(ImageIds=[image['ImageId']])
            return image

        except Exception as e:
            self.log_error(e)

    def create_task_queue(self, features, image_id):
        """Create a SQS task queue and populate the queue with a list of tasks"""
        try:
            client = self.boto3.client('sqs')

            # Create the queue
            queue_name = "beeworker_task_%s" % image_id
            response = client.create_queue(
                QueueName= queue_name,
                Attributes={
                    'MaximumMessageSize': '1024',
                    'ReceiveMessageWaitTimeSeconds': '20',
                    'VisibilityTimeout' : self.timeout           # number of seconds to allow a task to run before being deleted
                }
            )
            queue_url = response['QueueUrl']

            # Create tasks in the queue
            for feature in features:
                response = client.send_message(
                    QueueUrl = queue_url,
                    MessageBody = feature,
                )

            return queue_url

        except Exception as e:
            self.log_error(e)

    def create_result_bucket(self, image_id, result_count):
        """Create a S3 result folder within the beekeeper bucket"""
        try:
            client = self.boto3.client('s3')
            bucket_name = "beekeeper-%s" % image_id
            response = client.create_bucket(Bucket = bucket_name)

            # Set tags to identify the image id and the expected number of results
            response = client.put_bucket_tagging(
                Bucket = bucket_name,
                Tagging={
                    'TagSet': [
                        {'Key': 'beekeeper_expected_results', 'Value': str(result_count)}
                    ]
                }
            )

            return bucket_name

        except Exception as e:
            self.log_error(e)


    def create_spot_instances(self, image_id, max_workers, max_bid_price, sqs_task_queue_url, s3_result_bucket_name, debug):
        """Create worker instances"""
        try:
            # Setup user meta data
            user_data = {
                "sqs_task_queue_url": sqs_task_queue_url,
                "s3_result_bucket_name": s3_result_bucket_name,
                "master_instance_id": self.aws_instance_id,
                "behat_project_folder": self.behat_project_folder,
                "auto_shutdown": not debug,
                "timeout": self.timeout
            }
            user_data_base64 = base64.b64encode(json.dumps(user_data))

            # Create spot instances
            client = self.boto3.client('ec2')
            instance = self.get_instance()
            response = client.request_spot_instances(
                DryRun = False,
                SpotPrice = str(max_bid_price),
                InstanceCount = max_workers,
                Type = 'one-time',
                LaunchSpecification={
                    'ImageId': image_id,
                    'KeyName': instance['key_name'],
                    'UserData': user_data_base64,
                    'SubnetId': instance['subnet_id'],
                    'InstanceType': instance['instance_type'],
                    'Monitoring': {'Enabled': False},
                    'SecurityGroupIds' : [instance['security_group_id']]
                },
            )

            # Wait for instances to be running
            waiter = client.get_waiter('instance_running')
            waiter.wait(
                Filters=[
                    {'Name': 'image-id', 'Values': [image_id]},
                ],
            )

            return response

        except Exception as e:
            self.log_error(e)

    def get_spot_instance_price(self):
        """Get the current spot instance price"""

        try:
            client = self.boto3.client('ec2')
            instance = self.get_instance()

            product_description = 'Linux/UNIX (Amazon VPC)'

            response = client.describe_spot_price_history(
                StartTime = datetime.datetime.utcnow(),
                EndTime = datetime.datetime.utcnow(),
                InstanceTypes = [instance['instance_type']],
                Filters=[
                    {'Name': 'product-description', 'Values': [product_description]},
                ]
            )

            prices = response['SpotPriceHistory']
            lowest_price = 99999.99
            for price in prices:
                if float(price['SpotPrice']) < lowest_price:
                    lowest_price = float(price['SpotPrice'])

            result = {
                'instance_type': instance['instance_type'],
                'price': float(lowest_price)
            }

            return result

        except Exception as e:
            self.log_error(e)

    def get_volume(self):
        """Get volume info"""
        try:
            client = self.boto3.client('ec2')
            response = client.describe_volumes(
                Filters=[
                    {'Name': 'attachment.instance-id', 'Values': [self.aws_instance_id] },
                ],
            )
            return response

        except Exception as e:
            self.log_error(e)

    def download_results(self, image_id):
        """Monitor the progress of a test and download results as they become ready"""

        # Instantiate an S3 client and define some variables
        client = self.boto3.client('s3')
        bucket_name = 'beekeeper-' + image_id
        result_folder = self.behat_result_folder + '/' + image_id
        downloaded_files = []

        # Check S3 bucket for result files.
        response = client.list_objects(
            Bucket = bucket_name
        )

        # Download to local folder if results found.
        if 'Contents' in response:
            contents = response['Contents']
            for content in contents:
                filename = content['Key']
                destination = result_folder + '/' + filename
                client.download_file(bucket_name, filename, destination)
                response = client.delete_object(
                    Bucket=bucket_name,
                    Key=filename,
                )
                downloaded_files.append(filename)
        return downloaded_files


    def initialize_monitoring(self, image_id):
        """Initialize steps for monitor"""

        client = self.boto3.client('s3')
        bucket_name = 'beekeeper-' + image_id
        total_tasks = 0
        completed_tasks = 0

        # Get the total number of tasks which is stored in a tag in the s3 bucket
        try:
            response = client.get_bucket_tagging(
                Bucket = bucket_name
            )
            total_tasks = self.get_tag_value(response['TagSet'], 'beekeeper_expected_results')
        except Exception as e:
            return None

        # Check if local result folder was already created
        result_folder = self.behat_result_folder + '/' + image_id
        if (os.path.isdir(result_folder)):
            # Result folder already exist. Count the number of result files currently in there
            listing = glob.glob(result_folder + '/*.result')
            if listing:
                completed_tasks = len(listing)
        else:
            # Create the result folder
            os.makedirs(result_folder)

        results = {
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks
        }

        return results

    def cleanup(self, image_id):
        """Cleanup"""

        # Search for the latest AMI image if none was given
        if not image_id:
            try:
                image = self.get_snapshot()
                image_id = image['image_id']
            except Exception as e:
                self.log_error(e)
                click.echo('Cannot find image ID for instance %s.' % self.aws_instance_id)
                exit()

        try:
            # Current details of the current AMI image
            image = self.get_snapshot()
            image_id = image['image_id']
            snapshot_id = image['snapshot_id']
            queue_name = "beeworker_task_" + image_id
            bucket_name = 'beekeeper-' + image_id

            # Deregister AMI
            client = self.boto3.client('ec2')
            client.deregister_image(ImageId = image_id)
            click.echo("Deregistered AMI Image: %s" % image_id)

            # Delete Snapshot
            client.delete_snapshot(SnapshotId = snapshot_id)
            click.echo("Deleted Snapshot: %s" % snapshot_id)

            # Get task queue URL
            client = self.boto3.client('sqs')
            response = client.get_queue_url(QueueName = queue_name)
            queue_url = response['QueueUrl']

            # Delete the task queue
            response = client.delete_queue(
                QueueUrl = queue_url
            )
            click.echo("Deleting task queue: %s" % queue_url)

            # Delete S3 bucket
            client = self.boto3.client('s3')
            response = client.delete_bucket(
                Bucket=bucket_name
            )
            click.echo("Deleting S3 bucket: %s" % bucket_name)

        except Exception as e:
            self.log_error(e)

    def get_storage_price(self, region, storage_type = 'ebsssd'):
        """Get storage price

        Args:
            region (str): AWS region code
            storage_type: AWS storage type. Default to ebs ssd

        Returns:
            float: price of storage per GB-Month
        """

        # Assume a higher price for storage if current prices cannot be retrieved
        price = 0.15

        try:
            response = urllib2.urlopen('http://info.awsstream.com/storage.json')
            data = json.load(response)

            for record in data:
                if record['region'] == region and record['kind'] == storage_type:
                    price = record['price']
                    break

        except Exception as e:
            # Error out quietly if current storage cost cannot be retrieved
            pass

        return price
