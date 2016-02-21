import datetime
import time
import click
import os
import ConfigParser
import fnmatch
import paramiko
import inspect
import glob
import subprocess
import re
import operator

class Beekeeper(object):
    """Class to hold global configuration settings and general methods"""

    def __init__(self, profile='default'):
        # Read Beekeeper configuration file
        config_file = os.path.expanduser('~') + '/.beekeeper/config.ini'
        parser = ConfigParser.RawConfigParser()
        parser.read([config_file])

        # Define and set class variables for the default profile first
        default = dict(parser.items('default'))

        try:
            self.profile = 'default'
            self.aws_access_key_id = default['aws_access_key_id']
            self.aws_secret_access_key = default['aws_secret_access_key']
            self.aws_region = default['aws_region']
            self.aws_instance_id = default['aws_instance_id']
            self.behat_project_folder = default['behat_project_folder']
            self.behat_result_folder = default['behat_result_folder']
            self.max_workers = default['max_workers']
            self.max_bid_price = default['max_bid_price']
            self.ssh_config_host = default['ssh_config_host']
            self.timeout = default['timeout']
        except KeyError as e:
            click.echo('ERROR: %s not defined in the [default] region of your '
                '~/.beekeeper/config.ini file.' % e)
            exit()

        # Define class variable instance which will be used to cache instance data
        self.instance = None

        # Override default values if a profile is given
        if profile in parser.sections():
            self.profile = profile
            for key, value in parser.items(profile):
                setattr(self, key, value)
        elif profile and profile not in parser.sections():
            click.echo('Profile "%s" not found. Using default profile.' % profile)

    def get_ssh_connection(self):
        """Get a ssh connection to make remote ssh calls

        Returns:
            object: ssh object
        """

        try:
            ssh_config = paramiko.SSHConfig()
            ssh_config.parse(open(os.path.expanduser('~') + '/.ssh/config'))
            o = ssh_config.lookup(self.ssh_config_host)

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.load_system_host_keys()
            ssh.connect(o['hostname'], username=o['user'], key_filename=o['identityfile'])

            return ssh
        except Exception as e:
            click.echo('ERROR: Cannot ssh into %s. Please verify your ~/.ssh/config file is '
                'configured properly.' % self.ssh_config_host)
            exit()

    def timestamp(self, format = "%Y-%m-%d %H:%M:%S UTC", utc = True):
        """Get the current time

        Args:
            format (str): time display format
            utc (bool): True = UTC, False = Local

        Returns:
            str: formatted time
        """

        if utc:
            return datetime.datetime.utcnow().strftime(format)
        else:
            return datetime.datetime.now().strftime(format)

    def elapsed_time(self, start_time):
        elapsed_seconds = int(time.time() - start_time)
        minutes = int(elapsed_seconds / 60)
        if minutes == 0:
            seconds = elapsed_seconds
        else:
            seconds = elapsed_seconds % minutes

        formatted = '%dm %ds' % (minutes, seconds)
        return formatted

    def get_features(self, feature_folder):
        """Get a list of Behat feature files

        Args:
            feature_folder (str): path where Behat feature files are found

        Returns:
            list: of Behat feature files
        """

        matches = []
        for root, dirnames, filenames in os.walk(feature_folder):
            for filename in fnmatch.filter(filenames, '*.feature'):
                matches.append(filename)
        return matches

    def get_tag_value(self, tags, key):
        """Return the value of a AWS tag

        Args:
            tags (list): list of JSON formatted key-value pairs
            key (str): the key to get the value for

        Returns:
            str: value of given key
        """

        value = None
        # Iterate list looking for the key
        for tag in tags:
            if tag['Key'] == key:
                value = tag['Value']
                break
        return value

    def log_error(self, error):
        """Log errors"""
        method = inspect.stack()[1][3]
        path = inspect.stack()[1][1]
        filename_ext = os.path.basename(path)
        filename, ext = os.path.splitext(filename_ext)
        click.echo("Error in %s.%s(): %s" % (filename, method, error))

    def summarize_results(self, image_id):
        """Summarize all the result files into a dictionary which can then be outputted tp the screen
        or to a file

        Args:
            image_id (str): image_id of a Beekeeper run

        Returns:
            list: summarized results
        """

        # Get a list of result files in local directory
        results_path = '%s/%s/*.result' % (self.behat_result_folder, image_id)
        listing = glob.glob(results_path)

        if not listing:
            return None

        # Summarize each result file into a detail line
        details = {}

        # Setup a dictionary to hold the totals
        totals = {
            'scenarios': {'total': 0, 'passed': 0, 'failed': 0},
            'steps': {'total': 0, 'passed': 0, 'failed': 0, 'skipped': 0},
        }

        # Iterate each result file
        for full_path in listing:
            basename = os.path.basename(full_path)
            feature_name = basename.split('.feature.result')[0]

            # Setup nested dictionary
            details[feature_name] = {
                'scenarios': {},
                'steps': {}
            }

            # Get the last 3 lines from the result file which contains the summary we need
            tail = subprocess.Popen(['tail', '-n', '3', full_path], stdout=subprocess.PIPE)
            for line in tail.stdout:
                for stats_type in {'scenarios', 'steps'}:
                    stats_regex = '\d+(?=\s%s?)' % stats_type
                    stats_matched = re.search(stats_regex, line)
                    if stats_matched:
                        details[feature_name][stats_type]['total'] = int(stats_matched.group(0))
                        totals[stats_type]['total'] += int(stats_matched.group(0))
                        for result_type in {'passed', 'failed', 'skipped'}:
                            result_regex = '\d+(?=\s%s)' % result_type
                            matched = re.search(result_regex, line)
                            if matched:
                                details[feature_name][stats_type][result_type] = int(matched.group(0))
                                totals[stats_type][result_type] += int(matched.group(0))
                            else:
                                details[feature_name][stats_type][result_type] = 0
        sorted_details = sorted(details.items(), key=operator.itemgetter(0))
        results = {
            'details': sorted_details,
            'totals': totals
        }
        return results

    def available_reports(self):
        """Get a list of available reports"""
        listing = glob.glob(self.behat_result_folder + '/*')

        if not listing:
            return None

        # Sort the list by most recent
        results = {}
        for full_path in listing:
            basename = os.path.basename(full_path)
            results[basename] = os.path.getctime(full_path)

        sorted_results = sorted(results.items(), key=operator.itemgetter(1), reverse=True)

        return sorted_results