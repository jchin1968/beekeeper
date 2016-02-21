#Beekeeper
Beekeeper is a command line tool for running Behat tests in parallel using Amazon Web Services (AWS). 

The primary goal for Beekeeper is to reduce long Behat runtimes from hours to just minutes. Running Behat tests can take
a long time because test scenarios are executed sequentially. The more test scenarios you have, the longer it will take
to complete. For a complex website with lots of scenarios, a Behat run can take over an hour or more to finish.

Beekeeper also helps a Behat process recover when a test scenario hangs. It's been been noticed when
[PhantomJS](http://phantomjs.org) is used to run headless Behat scenarios involving Javascript, some scenarios would 
occassionally hang for no apparent reason. [Beeworker](https://github.com/jchin1968/beeworker) (a component of 
Beekeeper) will automatically kill a hanging process and restart a test.

#How It Works
By default, when you run a Behat test, all the feature files containing your Behat scenarios are queued (internally
within the application) and executed sequentially by a single process on that server. With Beekeper, it will distribute
the feature files across many servers. The general process is as follows:

1. A list of Behat feature files are queued on AWS SQS services
1. A snapshot (i.e. AWS AMI image) is made from the master instance containing your test environment
1. Multiple Beeworkers (i.e. AWS EC2 instances using the AMI image) are then spun up
1. Once a Beeworker boots up, it retrieves a single feature file from SQS and executes it using the standard  Behat
   command. The results of the test are stored in an AWS S3 Bucket and Beeworker retrieves another feature file from SQS
   to work on.
1. As the Beeworkers are running, Beekeeper download the results from S3 into it's local environment   
1. Once the queue in SQS is empty, each Beeworker shuts itself down and Beekeeper cleans up afer itself by deleting the
   AMI image, SQS queue and EC2 instances that were just created specifically for the test
1. Beekeeper consolidate all the results from the multiple workers into a summary report

#Requirements
* AWS credentials (i.e. access id and secret key) with full access to EC2, SQS and S3
* A single AWS instance running Linux containing the entire test environment i.e. Apache, PHP, MySQL and Behat installed 
  on a single server. This instance will be referred to as the Master instance
* Behat configured to run in headless mode i.e. using PhantomJS or Xvfb. See FAQ.md for instructions.
* Beeworker installed on the Master instance. Beeworker is a small application that 
* A separate environment (i.e. local desktop) to install Beekeeper. While only tested on a Linux environment, Beekeeper
  should work in Windows or Mac running Python 2.7.
* SSH access from your Beekeeper environment to the master instance. This is necessary since Beekeeper SSH into the 
  master instance to get a current list of Behat feature files.

#Installation
##For Ubuntu and Debian Based Distros
* apt-get update
* apt-get install python-pip git
* git clone https://github.com/jchin1968/beekeeper
* cd beekeeper
* pip install .

##For RHEL, Centos and Fedora
* yum install python-pip git
* git clone https://github.com/jchin1968/beekeeper
* cd beekeeper
* pip install .

#Configuration
Create a file named config.ini in a folder named .beekeper in your your home directory. ie. ~/.beekeeper/config.ini

This configuration file will need to contain the following [default] section and key-value pairings. The key values
provided are, of course, just examples. You will need to adjust for your own project.

    [default]
    aws_access_key_id = {Your AWS Access Key ID} 
    aws_secret_access_key = {Your AWS Secret Access Key}
    aws_region = ap-southeast-1
    aws_instance_id = i-1234abcd
    behat_project_folder = /home/joe/behat/customer1
    behat_result_folder = /home/joe/behat-results/customer1
    max_workers = 4
    max_bid_price = 0.2500
    timeout = 120
    ssh_config_host = aws-customer1-master-instance

Note:

* behat_project_folder is typically the one containing your behat.yml file and the features subfolder
* behat_result_folder is where the Behat generated result files will be stored. Each time Beekeeper is run, a new
  subfolder is created to hold that result. 
* max_workers is the number of AWS instances that will be created in a test.
* max_bid_price (in USD) is the maximum AWS spot instance price Beekeeper will automatically accept before prompting
  you for confirmation to proceed
* timeout refers to the amount of time (in seconds) Behat should spend processing a single feature file before
  deciding the process has hung, automatically killing it and put that feature file back into the work queue to be
  processed again
* ssh_config_host is the host name defined in your ~/.ssh/config file that points to the master instance. Your ssh
  config file will contain an entry similar to the following:


    Host aws-customer1-master-instance
        Hostname 111.222.111.222
        Port 22
        User ubuntu
        IdentityFile ~/.ssh/aws_generated_pem_file.pem

You can add additional profiles to the config file by defining a section i.e. [profile2] and key-value pairs that
differs from the default. For example:
    
    [profile2]
    aws_instance_id = i-9876ab12
    behat_project_folder = /var/www/drupal/sites/default/behat-tests
    ssh_config_host = customer2-drupal-stage
    
#General Usage

To see a list of commands, just enter beekeeper by itself on the command line i.e.

    beekeeper
    
Type the following to see detailed :
    
    beekeeper COMMAND --help
    
Most Beekeeper commands follow this syntax:

    beekeeper COMMAND [PROFILE] options
    
where COMMAND is 

Where [PROFILE] refers to the profile you defined in ~/.beekeeper/config.ini. If you do not specify a profile, [default]
will be used.

##Running Beekeeper Tests
Before using Beekeeper, make sure you are able to run Behat tests in headless mode on your test environment. It is fine
to have Behat result errors (i.e. test assertion errors), you just can't have things like compile errors where the Behat
process does not finish properly.

To verify you have set up your Beekeeper configuration properly, enter:

    beekeeper status
    
You should see some general information about your default instance. If the state of the instance is stopped, you can
start it by entering:

    beekeeper start
    
To stop it, enter:
    
    beekeeper stop
    
To get an estimated cost of running a test, enter:
    
    beekeeper cost
       
To run an actual test, enter:
    
    beekeeper test
    
Once the beeworkers are working and, for whatever reason, the beekeeper process is stopped (i.e. entering ctrl-c), you
can resume monitoring and downloading results by entering:

    beekeeper monitor

Once the test has completed, enter the following to see a summary of the results:
    
    beekeeper report

Beekeeper tries to clean up after itself at the end of each test. But, if there are lingering AMI images or SQS queues,
try entering:

    beekeeper cleanup 
    
If that doesn't work, then you will have to manually remove them using the AWS GUI Console. 

To see a list of EC2 instances in your default region, enter:

    beekeeper list
    
Creating a snapshot of an instance for the first time can take a while (i.e. over an hour). Subsequent snapshots,
though, are quite fast (i.e. minutes) since they are incremental backups instead of a full backup that is performed 
for the first time. If you know you
have an upcoming test planned, you can create a snapshot now so when you run the actual beekeeper test, that subsequent
snapshot will be relatively fast. 

    
##Caveats
Beekeeper is still in early development so there are a number of caveats to consider before using it.

* The entire test environment is self contained inside one AWS instance. So, services like Apache, MySQL, Redis/Memcache
  and the sites/files folder (for Drupal projects) should all be on the same server. This also mean AWS services like 
  RDS and Elasticache are not supported yet.
* Beekeeper should not be installed on the same server as your test environment.  
* You have a headless Behat setup which does not open any graphical browser windows. Read FAQ.md for instructions on how  
  to run Behat tests on a headless server using PhantomJS.
* Beekeeper only support AWS right now but I am looking at whether this model will work with other cloud providers like
  Microsoft Azure, Linode and DigitalOcean as well as environments like Docker, VMware and VirtualBox. 
* Since each feature file can spin up it's own AWS instance to run in parallel, ideally, you want many short
  feature files rather than a few really long ones.
* The time to snapshot and clone multiple AWS instances takes around 3-5 minutes. So your current, single server Behat
  run should takes longer than 5 minutes in order to make it worthwhile to use Beekeeper
* Your Behat scenarios should be isolated and not dependent on results from a different feature file.
* Beekeeper uses AWS spot instance to minimize cost. So, your Behat tests may fail to complete if AWS abruptly 
  terminates the spot instances due to a spot price increase.
* Beekeeper tries to cleanup after itself after each test but you should still check your AWS console for old snapshots,
  instances, etc. so you are not charged for them.
* Beekeeper was developed to run Drupal Behat tests using the Drupal Behat Extension. But, there is no reason why it
  can't run general Behat tests on a non-Drupal project or even PHPUnit tests with some minor tweaking. In fact, I hope 
  to further develop Beekeeper to not just run PHP tests applications but any application that can benefit from 
  parallization using AWS services