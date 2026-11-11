# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# The backup server: Python 3.11, rsync 3.2.7, sshd (agents push here) and an
# operator account. The wheel is installed by run.sh.
FROM debian:12
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends python3 python3-venv rsync openssh-server openssh-client sshpass ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /run/sshd /srv/backup \
 && useradd -m -s /bin/bash operator && chown operator:operator /srv/backup
# Test harness only: the operator's own ssh/scp answer the hosts' password prompts
# with $SSHPASS (bootstrap, upgrade, remove). The control key never prompts.
COPY sshpass-wrapper /usr/local/bin/ssh
COPY sshpass-wrapper /usr/local/bin/scp
RUN chmod 755 /usr/local/bin/ssh /usr/local/bin/scp
CMD ["/usr/sbin/sshd", "-D", "-e"]
