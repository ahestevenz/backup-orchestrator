# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
#
# A Debian 12 source host with systemd as PID 1 (the agent's jobs are systemd units).
FROM debian:12
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends systemd systemd-sysv openssh-server sudo rsync ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# Test harness only: the admin account logs in with a password (given by sshpass on
# the server) and may sudo without a prompt, because `ssh -t` runs without a terminal here.
RUN useradd -m -s /bin/bash admin && echo 'admin:admin-pass' | chpasswd \
 && echo 'admin ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/test-harness && chmod 0440 /etc/sudoers.d/test-harness \
 && useradd -m -s /bin/bash alice && useradd -m -s /bin/bash bob \
 && sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config \
 && systemctl enable ssh
STOPSIGNAL SIGRTMIN+3
CMD ["/lib/systemd/systemd"]
