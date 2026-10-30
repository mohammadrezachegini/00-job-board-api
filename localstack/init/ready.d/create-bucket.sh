#!/bin/bash
set -euo pipefail
awslocal s3 mb "s3://${AWS_STORAGE_BUCKET_NAME}"