#Beekeeper FAQ

##What Is Headless Behat And Why Is It Necessary?
Behat scenarios tagged with @javascript will normally open up a graphical window containing your default browser in
which to execute the test, simulating the steps a real human would do. However, if your test environment is a remote
server accessed via SSH, then it's generally not possible to run applications requiring a graphical window. There is a
way around this which is to run an xserver on your local machine and enable x11 forwarding on your SSH client.    


##Setting Up Headless Behat
There are two ways (that I know of) to setup a headless Behat environment. One method is to use PhantomJS and the other
is to use Xvfb plus the browser (i.e. Firefox, Chrome) of your choice.


##What kind of runtime improvement can I expect to see?
Assume each Behat feature file takes 2 minutes to complete and you have 60 of them. Running them sequentially on a
single server will take 120 minutes or 2 hours. 

If you spin up 10 instances so that each instance is executing 6 feature files, the total runtime is reduced to 17 
minutes. 3 minutes to make a snapshot of the master instance, 1 minute for the spot request to be fulfilled, 
another minute for all 10 spot instances to startup and 12 minutes to run 6 tests on each instance. (3 + 1 + 1 + 12)
 
If you had 20 instances running, the total runtime will be 11 minutes. (3 + 1 + 1 + 6)

You can calculate the estimated runtime using this formula:
  
    Estimated Runtime = Fixed Startup Time + (Number of Feature Files x Runtime Per File / Number of Instances)

where Fixed Startup Time is usually around 5 minutes.

Note: Snapshots on AWS are incremental. The first time you make a snapshot of an instance, the process can take over
an hour to complete. However, subsequent snapshots are very fast since only the blocks that have changed will be 
saved. Therefore, if you know you have some upcoming tests to run, you can take a snapshot (i.e. beekeeper snapshot) 
beforehand (i.e. a few hours or even a day before) so when you run the actual tests, the snapshot process runs
relatively quick.  

##Isn't it expensive to run so many instances?
Not really. By charging hourly usage, Amazon has made parallel computing incredibly cheap. Let's assume your test
instance is a m4.large located in region "ap-southeast-1" (Asia Pacific Singapore) and you have a 30 GB EBS
general purpose volume attached to it.

There are a number of AWS services that Beekeeper consumes and the prices in region ap-southeast-1 on Nov. 2, 2015 for
them are:

 * $0.095 GB-month for S3 storage 
 * $0.12 GB-month for an EBS General Purpose volume 
 * $0.50 per 1 million SQS requests with the first 1 million requests per month free.
 * Around $0.025 per hour spot price for a m4.large (running Linux). In the past 3 months, the spot price did hover
   around $0.04 for a few days and even peaked at $0.06. So, to be conservative with our budgeting, we'll use an
   instance price of $0.04 per hour. For comparison, the on-demand price for a m4.large is $0.187 per hour. 
 * Free Data Transfer for traffic within the same AWS region and $0.120 per GB (up to 10TB) for data out to the
   Internet. The first GB is actually free but let's assume it's already used by other services i.e. web hosting. 

To calculate the EC2 charges, we simply multiply the spot instance price by the number of spot instances. From our
example above, if we use 20 spot instances running for 11 minutes, the cost will be: 20 x $0.04 = $0.80.

To calculate EBS storage costs, we have to calculate GB-Hours used and then convert it to GB-Month:

 * The number of GB-Hours used is 30 GB/instance x 20 instances x 1 hour = 600 GB-Hours
 * A month has 744 hours (assuming 31 days) therefore, 600 GB-Hours is equal to 600 / 744 = 0.8065 GB-Month
 * 0.8065 GB-Month x $0.12 GB-Month = $0.0968.
 
S3 storage charge is calculated similarly to EBS storage. So, a 30 GB AMI Image used for 1 hour will be
30 GB-Hour / 744 * $0.095 = $0.0038.

The number of SQS requests will be around 150 which is well within the first million free. 60 push requests (1 for
each feature file), 60 pull requests, plus a few more for housekeepeing ie. creating and deleting the queue, etc.

Data transfers within a region is free. So, creating an AMI image, spinning up new instances, storing results in S3 will
not incur any data transfer charge. There is a charge though for downloading the Behat results from S3 to your own
computer. Assume each Behat feature result is 2 MB in size (which is quite large). Therefore, 60 results will equal to
120 MB (or 0.120 GB) of data transfer at a costs of $0.0144 ($0.120 per GB x 0.120 GB)     

So, adding up the various charges:

    Total = EC2 + EBS + S3 + SQS + Data Transfer 
          = $0.80 + $0.0968 + $0.0038 + $0 + $0.0144 
          = $0.915

##Why spin up multiple instances? Couldn't you just tag Behat scenarios to different Apache virtual hosts or use Selenium Grid on a single server?
For a content-rich website with a large database (i.e. 5+ GB) or lots of media files, it takes a long time to create
duplicate environments since the duplication process is sequential.  

For example, if you wanted to create 10 separate environments so you can run 10 Behat processes simultaneously, you
would need to create 10 different databases, all being identical except for the schema name. The fastest way to
do this is to simply copy-and-paste the raw database files and do some renaming. If your database file is 5 GB then
you would need to copy 50 GB of data. On my SSD laptop, 1 GB of files takes 15 seconds to copy. So, 50 GB would take
around 750 seconds or 12.5 minutes to complete. Then, you still need to run the actual Behat test itself which, 
using the example described above, 10 instances will take 12 minutes to complete. So, now you are at 24 minutes versus
17 minutes using Beekeeper and AWS. If you wanted to run 20 Behat processes, the time to replicate all those databases
will be 1500 seconds or 25 minutes which is clearly not scalable.
  
Another advantage with using Beekeeper and simply cloning (i.e. create an AMI image) the whole environment is you don't
need to reconfigure your whole test environment to support parallel testing. If you can run Behat as a single process
then it will work in parallel.

The bigger issue with getting Behat to run in parallel is getting it to run in a headless environment. 


    