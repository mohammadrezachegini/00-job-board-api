# A "fresh Ubuntu 26.04" for testing scripts/bootstrap.sh: a normal user with sudo, nothing else.
FROM ubuntu:26.04
RUN apt-get update \
 && apt-get install -y --no-install-recommends sudo \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash dev \
 && echo "dev ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/dev \
 && chmod 0440 /etc/sudoers.d/dev
USER dev
WORKDIR /home/dev
