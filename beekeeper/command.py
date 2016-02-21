from __future__ import print_function
import aws
import click
import time
import sys
import re

# Define a list of existing AWS regions
# TODO: find a way to update this list automatically
aws_regions = [
    'us-east-1', 'us-west-1', 'us-west-2', 'eu-west-1', 'us-central-1', 'ap-southeast-1',
    'ap-southeast-2', 'ap-northeast-1', 'sa-east-1', 'us-gov-west-1'
]

@click.group()
def cli():
    """Beekeeper is a command line interface for running parallel Behat tests on Amazon Web Services"""

@cli.command()
@click.argument('region', required=False, type=click.Choice(aws_regions))
def list(region):
    """Show available instances in a region."""
    service = aws.AWS()

    if not region:
        region = service.aws_region

    instances = service.list_instances(region)

    if instances:
        fmt = '{0:15} {1:12} {2:10} {3}'

        click.echo()
        click.echo(fmt.format('INSTANCE ID', 'TYPE', 'STATE', 'NAME'))
        click.echo(fmt.format('-----------', '----', '-----', '----'))

        for server in instances:
            click.echo(fmt.format(server['instance_id'], server['instance_type'], server['state'], server['name']))
        click.echo()
    else:
        click.echo("No instance found for region: %s" % region)
        click.echo()


@cli.command()
@click.argument('profile', default='default')
def status(profile):
    """Get the status of an instance"""
    service = aws.AWS(profile)

    # Display basic instance detail
    instance = service.get_instance()
    if instance:
        fmt = '{0:30}: {1}'
        click.echo()
        click.echo(fmt.format('Beekeeper Profile', service.profile))
        click.echo(fmt.format('EC2 Instance ID', instance['instance_id']))
        click.echo(fmt.format('Tagged Name', instance['name']))
        click.echo(fmt.format('Type', instance['instance_type']))
        click.echo(fmt.format('State', instance['state']))
        click.echo(fmt.format('Availability Zone', instance['availability_zone'] ))
        click.echo(fmt.format('Volume ID', instance['volume_id'] ))
        click.echo(fmt.format('Volume Size', str(instance['volume_size']) + ' GB' ))
        click.echo(fmt.format('Security Key Name', instance['key_name'] ))
        click.echo(fmt.format('Security Group ID', instance['security_group_id'] ))
        click.echo()
    else:
        click.echo('No instance found')
        exit(1)

    # Display the latest AMI image for the volume id
    image = service.get_snapshot()
    if image:
        click.echo(fmt.format('AMI Image ID', instance['image_id']))
        click.echo(fmt.format('Create', image['created_humanize'] + ' (at ' + image['created_datestring'] + ')' ))
        click.echo(fmt.format('State', instance['state']))
        click.echo()
    else:
        click.echo(fmt.format('AMI Image ID', 'None found that were created with Beekeeper'))
        click.echo()
        exit()

    # Display queue information
    queue = service.get_task_queue(image['image_id'])
    if queue:
        click.echo(fmt.format('Messages in task queue', queue['message_count']))
        click.echo()
    else:
        click.echo(fmt.format('Messages in task queue', 'Not Available'))
        click.echo()


@cli.command()
@click.argument('profile', default='default')
def snapshot(profile):
    """Create a snapshot of an instance."""
    service = aws.AWS(profile)
    print ('Creating AMI Image...', end="")
    sys.stdout.flush()
    image = service.create_snapshot()
    click.echo('completed. The AMI ID is %s' % image['ImageId'])
    return image['ImageId']


@cli.command()
@click.argument('profile', default='default')
@click.option('--max_workers', type=int, help='Maximum number of AWS instances to create')
@click.option('--detail', default=False, is_flag=True, help='Show cost estimate in detail')
def cost(profile, max_workers, detail):
    """Estimate the cost of running a test"""

    service = aws.AWS(profile)

    max_workers = max_workers if max_workers else int(service.max_workers)

    # Calculate EC2 cost
    spot_result = service.get_spot_instance_price()
    ec2_cost = spot_result['price'] * max_workers

    # Calculate EBS volume used
    volume = service.get_volume()
    volume_size = float(volume['Volumes'][0]['Size'])
    total_volume = volume_size * max_workers

    # Get base storage price
    ebs_storage_price = service.get_storage_price(service.aws_region)

    # Calculate EBS cost
    # EBS charges are per hour so 50GB x 20 servers x 1 hour = 1000 GB-hours utilized
    # If rate is $0.12 GB-Month, then cost = 1000 * 0.12 * (1 / 744) = $0.16
    ebs_cost = total_volume / 744 * ebs_storage_price

    # Calculate total
    total = ec2_cost + ebs_cost

    # Display estimated costs for running one test
    fmt = '{0:30}: {1}'
    if detail:
        click.echo()
        click.echo('Estimated Cost')
        click.echo('--------------')
        click.echo(fmt.format('Beekeeper Profile', service.profile))
        click.echo(fmt.format('Number of Workers', max_workers))
        click.echo(fmt.format('Region', service.aws_region))
        click.echo()
        click.echo(fmt.format('Instance Type', spot_result['instance_type']))
        click.echo(fmt.format('Current Spot Price', '$%.4f per hour' % spot_result['price']))
        click.echo(fmt.format('EC2 costs', '$%.4f' % ec2_cost))
        click.echo()
        click.echo(fmt.format('EBS Volume Size', '%s GB per instance' % volume_size))
        click.echo(fmt.format('Total Volume', '%s GB' % total_volume))
        click.echo(fmt.format('Base Storage Price', '$%.4f GB-Month' % ebs_storage_price))
        click.echo(fmt.format('EBS costs', '$%.4f' % ebs_cost))
        click.echo()
        click.echo(fmt.format('TOTAL ESTIMATED COST', '$%.4f' % total))
        click.echo()
    else:
        click.echo('Current Spot Price for %s is $%.4f per hour' % (spot_result['instance_type'], spot_result['price']))
        click.echo('Estimated cost for running %d instances plus storage charge is $%.4f' % (max_workers, total))
    return spot_result['price']


@cli.command()
@click.argument('profile', default='default')
@click.option('--max_workers', type=int, help='Maximum number of AWS instances to create')
@click.option('--max_bid_price', type=float, help='Maximium bid price for a spot instance')
@click.option('--debug', default=False, is_flag=True)
@click.pass_context
def test(ctx, profile, max_workers, max_bid_price, debug):
    """Deploy beeworker instances and start testing"""

    service = aws.AWS(profile)

    click.echo('\n--- CHECK ---')
    click.echo('Process started at %s' % service.timestamp('%H:%M:%S', False) )
    start_time = time.time()

    # Use default settings if optional values not provided
    max_workers = max_workers if max_workers else int(service.max_workers)
    max_bid_price = max_bid_price if max_bid_price else float(service.max_bid_price)

    # Check if the master instance is running.
    instance = service.get_instance()
    if instance['state'] == 'running':
        click.echo('Master instance is running')
    else:
        click.echo('Master instance not running. Exiting test.')
        exit()

    # SSH into the instance and get a list of Behat feature files
    ssh = service.get_ssh_connection()
    command = "ls -R %s |grep .feature$" % service.behat_project_folder
    stdin, stdout, stderr = ssh.exec_command(command)
    features = stdout.read().splitlines()
    if features:
        click.echo('%d Behat feature files found.' % len(features))
    else:
        click.echo('No Behat feature file found in %s. Exiting test.'
            % service.behat_project_folder)
        exit()

    # Invoke the cost command to check the current price for a spot instance
    # and to generate a cost estimate
    current_spot_price = ctx.invoke(cost, profile=profile, max_workers=max_workers)
    if current_spot_price > max_bid_price:
        click.secho('Note: Current spot price of $%.4f exceeds your maximum bid price of $%.4f.'
            % (current_spot_price, max_bid_price), fg='red', bold=True)
        if not click.confirm('Do you want to continue?'):
            click.echo('Exiting test')
            exit()

    click.echo('\n--- SETUP ---')

    # Invoke the snapshot command to create a snapshot of the master instance
    image_id = ctx.invoke(snapshot, profile=profile)
    click.echo('Elapsed time is %s' % service.elapsed_time(start_time))

    # Create and populate the task queue.
    sqs_task_queue_url = service.create_task_queue(features, image_id)
    click.echo('Created SQS Task Queue and added %d tasks' % len(features))

    # Create an S3 bucket to hold the test results
    s3_result_bucket_name = service.create_result_bucket(image_id, len(features))
    click.echo('Created S3 Result Bucket')

    # Create the workers
    print('Requesting %d spot instances...' % max_workers, end="")
    sys.stdout.flush()
    response = service.create_spot_instances(image_id, max_workers, max_bid_price, sqs_task_queue_url, s3_result_bucket_name, debug)
    click.echo('fulfilled')
    click.echo('Elapsed time is %s' % service.elapsed_time(start_time))

    click.echo('\n--- WORK ---')
    click.echo('%d workers launched and preparing to test' % max_workers)

    # Invoke the monitor command
    ctx.invoke(monitor, image_id=image_id)
    elapsed = int(time.time() - start_time)
    click.echo('Tests completed at %s. Total elapsed time is %s' % (service.timestamp('%H:%M:%S', False), service.elapsed_time(start_time)))

    # Invoke cleanup command
    click.echo('\n--- Cleanup ---')
    ctx.invoke(cleanup, image_id=image_id)

    # Generate a summary of the test results

    click.echo('\n--- REPORT ---')
    ctx.invoke(report, image_id=image_id)



@cli.command()
@click.argument('profile', default='default')
def start(profile):
    """Start an instance"""
    service = aws.AWS(profile)
    service.start_instance()
    click.echo('Starting instance %s' % service.aws_instance_id)


@cli.command()
@click.argument('profile', default='default')
def stop(profile):
    """Stop an instance."""
    service = aws.AWS(profile)
    service.stop_instance()
    click.echo('Stopping instance %s' % service.aws_instance_id)


@cli.command()
@click.argument('image_id')
@click.pass_context
def monitor(ctx, image_id):
    """Monitor progress and download results"""
    service = aws.AWS()

    # Initialize monitoring
    result_status = service.initialize_monitoring(image_id)

    # Exit monitoring if the initializing process failed
    if not result_status:
        click.echo('Failed to initialize monitoring. Exiting.')
        exit()

    total_tasks = int(result_status['total_tasks'])
    completed_tasks = int(result_status['completed_tasks'])
    remaining_tasks = total_tasks - completed_tasks

    print('Number of tests remaining...%d' % remaining_tasks, end="")
    sys.stdout.flush()
    while remaining_tasks > 0:
        try:
            downloaded = service.download_results(image_id)
            if downloaded:
                for filename in downloaded:
                    completed_tasks += 1
                    remaining_tasks = total_tasks - completed_tasks
                    print ("...%d" % remaining_tasks, end="")
                    sys.stdout.flush()
        except KeyboardInterrupt:
            click.echo('\nExiting monitor mode')
            exit()

        time.sleep(10)
        print(".", end="")
        sys.stdout.flush()
    click.echo()

@cli.command()
@click.argument('image_id', required=False, default=None)
@click.option('--only_failed', default=False, is_flag=True, help='Show only failed scenarios')
def report(image_id, only_failed):
    """Generate Behat result summary """
    service = aws.AWS()

    # If no image_id provided then display a list of available images from the result folder
    if not image_id:
        available = service.available_reports()

        if available == None:
            # No image folder found so exit
            click.echo('No results found')
            exit()

        if (len(available) == 1):
            # One image folder was found so use it
            image_id = available[0][0]
        else:
            # More then 1 image folder was found so present a list to the user to choose
            click.echo('\nAvailable Results to Report\n')
            line_format = '{0:3})  {1:12}  created  {2:}'
            for index, object in enumerate(available, start=1):
                click.echo(line_format.format(index, object[0], time.ctime(object[1])))
            click.echo()
            value = click.prompt('Enter a number', type=click.IntRange(1, len(available)))
            image_id = available[value-1][0]

    # Generate the results for the given image_id
    results = service.summarize_results(image_id)

    if results:
        header_fmt = '{0:35} {1:>9} {2:>5} {3:>5} {4:>7} {5:>5} {6:>5} {7:>5}'
        line_fmt = '{0:35} {1:9d} {2:6d} {3:6d} {4:7d} {5:6d} {6:6d} {7:7d}'
        click.echo()
        click.echo(header_fmt.format('Feature Name', 'Scenarios', 'Passed', 'Failed', 'Steps', 'Passed', 'Failed', 'Skipped'))
        click.echo(header_fmt.format('------------', '---------', '------', '------', '-----', '------', '------', '-------'))

        counter = 0
        for feature_file, values in results['details']:
            # If failed option flag is set and the scenario passed, don't show on report
            if only_failed and values['scenarios']['failed'] == 0:
                continue

            # Format the detail line
            detail_line = line_fmt.format(
                feature_file,
                values['scenarios']['total'],
                values['scenarios']['passed'],
                values['scenarios']['failed'],
                values['steps']['total'],
                values['steps']['passed'],
                values['steps']['failed'],
                values['steps']['skipped'],
            )

            # If a line contain failed scenarios then highlight it bold and red
            if values['scenarios']['failed']:
                click.secho(detail_line, fg='red', bold=True)
            else:
                click.echo(detail_line)

            # Count number of lines
            counter += 1

        # Show summary
        click.echo(header_fmt.format('', '---------', '------', '------', '-----', '------', '------', '-------'))
        detail_line = line_fmt.format(
            'TOTAL',
            results['totals']['scenarios']['total'],
            results['totals']['scenarios']['passed'],
            results['totals']['scenarios']['failed'],
            results['totals']['steps']['total'],
            results['totals']['steps']['passed'],
            results['totals']['steps']['failed'],
            results['totals']['steps']['skipped'],
        )
        click.echo(detail_line)
        click.echo('\nNumber of feature files: %d' % counter)
    else:
        click.echo('No results found')

@cli.command()
@click.argument('profile', default='default')
@click.option('--image_id', default=None, help='AWS AMI image ID')
def cleanup(profile, image_id):
    """Delete old snapshots and queues."""
    service = aws.AWS(profile)
    service.cleanup(image_id)


@cli.command()
@click.argument('profile', default='default')
@click.pass_context
def debug(ctx, profile):
    "Development test purpose only"

    service = aws.AWS()

    available = service.available_reports()
    if available:
        click.echo('\nAvailable Results to Report')
        line_format = '{0:3})  {1:16} {2:}'
        for index, object in enumerate(available, start=1):
            click.echo(line_format.format(index, object[0], time.ctime(object[1])))

    value = click.prompt('Enter a number', type=click.IntRange(1,4))
    print (available[value-1][0])