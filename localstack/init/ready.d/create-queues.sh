#!/bin/bash
set -euo pipefail

dlq_url=$(awslocal sqs create-queue --queue-name "${SQS_QUEUE_NAME}-dlq" --query QueueUrl --output text)
dlq_arn=$(awslocal sqs get-queue-attributes --queue-url "$dlq_url" --attribute-names QueueArn --query Attributes.QueueArn --output text)

cat > /tmp/queue-attributes.json <<EOF
{
  "VisibilityTimeout": "30",
  "RedrivePolicy": "{\"deadLetterTargetArn\":\"${dlq_arn}\",\"maxReceiveCount\":\"3\"}"
}
EOF

awslocal sqs create-queue --queue-name "${SQS_QUEUE_NAME}" --attributes file:///tmp/queue-attributes.json