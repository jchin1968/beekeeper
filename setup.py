from setuptools import setup

setup(
    name='beekeeper',
    version='0.1',
    description='A command line interface for running Behat tests in parallel using Amazon Web Services',
    keywords='aws amazon parallel behat test beekeeper beeworker',
    url='https://github.com/jchin1968/beekeeper',
    author='Joseph Chin',
    author_email='joe@beesuite.net',
    license='GPL2.0',
    packages=['beekeeper'],
    install_requires=[
        'boto3',
        'click',
        'arrow',
        'paramiko'
    ],
    entry_points='''
        [console_scripts]
        beekeeper=beekeeper.command:cli
    ''',
)
