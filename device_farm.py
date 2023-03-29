import datetime
import logging
import os
import random
import string
import sys
import time

import boto3
import requests

from configs.run_config import DEVICE_FARM_CONFIG
from constants.constants_dirs import ROOT_DIR
from utilities.generic_utils import run

# The following script runs a test through Device Farm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

test_name = "test_bundle.zip"


# All folder to zip
run("zip -r test_bundle.zip "
    "tests/ "
    "base/ "
    "configs/ "
    "pages/ "
    "test_case_management/ "
    "test_data/ "
    "utilities/ "
    "conftest.py "
    "pytest.ini "
    "constants/ "
    "requirements.txt")


client = boto3.client('devicefarm', 'us-west-2')

# To get all device pool arn
response = client.list_device_pools(
    type='PRIVATE',
    # You can get the project ARN by using the list-projects CLI command.
    arn='arn:aws:devicefarm:us-west-2:344041258662:project:ff697fda-f9e5-4341-9ef5-7a03b1f35a32'
)
pprint(response)

To get all testspec arn
response = client.list_uploads(
    arn='arn:aws:devicefarm:us-west-2:344041258662:project:ff697fda-f9e5-4341-9ef5-7a03b1f35a32',
    type='APPIUM_PYTHON_TEST_SPEC')
pprint(response)

unique = DEVICE_FARM_CONFIG['namePrefix'] + "-" + (datetime.datetime.today().strftime("%Y-%m-%d-%H-%M-%S")) + (
    ''.join(random.sample(string.ascii_letters, 8)))

logging.debug(f"The unique identifier for this run is going to be {unique} -- all uploads will be prefixed with this.")


def upload_df_file(filename, type_, mime='application/octet-stream'):
    response = client.create_upload(projectArn=DEVICE_FARM_CONFIG['projectArn'],
                                    name=(unique) + "_" + os.path.basename(filename),
                                    type=type_,
                                    contentType=mime
                                    )
    # Get the upload ARN, which we'll return later.
    upload_arn = response['upload']['arn']
    # We're going to extract the URL of the upload and use Requests to upload it
    upload_url = response['upload']['url']
    with open(filename, 'rb') as file_stream:
        logging.info(f"Uploading {filename} to Device Farm as {response['upload']['name']}... ")
        put_req = requests.put(upload_url, data=file_stream, headers={"content-type": mime})
        logging.info(' done')
        if not put_req.ok:
            raise Exception("Couldn't upload, requests said we're not ok. Requests says: " + put_req.reason)
    started = datetime.datetime.now()
    while True:
        logging.info(f"Upload of {filename} in state {response['upload']['status']} after " + str(
            datetime.datetime.now() - started))
        if response['upload']['status'] == 'FAILED':
            raise Exception(
                "The upload failed processing. DeviceFarm says reason is: \n" + response['upload']['message'])
        if response['upload']['status'] == 'SUCCEEDED':
            break
        time.sleep(5)
        response = client.get_upload(arn=upload_arn)
    logging.info("")
    return upload_arn


our_upload_arn = upload_df_file(app_file, app_type)
our_test_package_arn = upload_df_file(DEVICE_FARM_CONFIG['testPackage'], 'APPIUM_PYTHON_TEST_PACKAGE')
logging.info(str(our_upload_arn) + str(our_test_package_arn))
# Now that we have those out of the way, we can start the test run...
response = client.schedule_run(
    projectArn=DEVICE_FARM_CONFIG["projectArn"],
    appArn=our_upload_arn,
    devicePoolArn=pool_arn,
    name=unique,
    test={
        "type": "APPIUM_PYTHON",
        "testSpecArn": test_spec,
        "testPackageArn": our_test_package_arn
    }
)
run_arn = response['run']['arn']
start_time = datetime.datetime.now()
logging.info(f"Run {unique} is scheduled as arn {run_arn} ")

while True:
    response = client.get_run(arn=run_arn)
    state = response['run']['status']
    runstatus = response['run']['result']
    message = response['run']['status']
    if runstatus == 'FAILED':
        raise Exception(
            f" Run {unique} is {runstatus}, please check reportportal or device-farm for detailed logs, "
            f"total time " + str(
                datetime.datetime.now() - start_time))
    elif state == 'COMPLETED' or state == 'ERRORED':
        break
    else:
        logging.info(f" Run {unique} in state {state}, total time " + str(datetime.datetime.now() - start_time))
        time.sleep(10)
# except:
#     # If something goes wrong in this process, we stop the run and exit.
#
#     client.stop_run(arn=run_arn)
#     exit(1)
logging.info(f"Tests {runstatus} after " + str(datetime.datetime.now() - start_time))
logging.info("Pulling logs from device farm.....")
jobs_response = client.list_jobs(arn=run_arn)
# Save the output somewhere. We're using the unique value, but you could use something else
if not os.path.exists(ROOT_DIR + "/reports"):
    os.mkdir(ROOT_DIR + "/reports")
save_path = os.path.join(ROOT_DIR, 'reports', unique)
os.mkdir(save_path)
# Save the last run information
for job in jobs_response['jobs']:
    # Make a directory for our information
    job_name = job['name']
    os.makedirs(os.path.join(save_path, job_name), exist_ok=True)
    # Get each suite within the job
    suites = client.list_suites(arn=job['arn'])['suites']
    for suite in suites:
        for test in client.list_tests(arn=suite['arn'])['tests']:
            # Get the artifacts
            for artifact_type in ['FILE', 'SCREENSHOT', 'LOG']:
                artifacts = client.list_artifacts(
                    type=artifact_type,
                    arn=test['arn']
                )['artifacts']
                for artifact in artifacts:
                    # We replace : because it has a special meaning in Windows & macos
                    path_to = os.path.join(save_path, job_name, suite['name'], test['name'].replace(':', '_'))
                    os.makedirs(path_to, exist_ok=True)
                    filename = artifact['type'] + "_" + artifact['name'] + "." + artifact['extension']
                    artifact_save_path = os.path.join(path_to, filename)
                    logging.info("Downloading " + artifact_save_path)
                    with open(artifact_save_path, 'wb') as fn, requests.get(artifact['url'],
                                                                            allow_redirects=True) as request:
                        fn.write(request.content)
                    # /for artifact in artifacts
                # /for artifact type in []
            # / for test in ()[]
        # / for suite in suites
    # / for job in _[]
# done
logging.info("Finished execution on device farm")
