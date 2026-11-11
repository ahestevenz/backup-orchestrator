# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2018-2026 Ariel Hernandez (bleiben)
"""Email over SMTP with STARTTLS, standard library only (CLAUDE.md §6.14)."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from ..config import EmailConfig


def build(cfg: EmailConfig, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.from_
    msg["To"] = ", ".join(cfg.to)
    msg.set_content(body)
    return msg


def send(cfg: EmailConfig, subject: str, body: str) -> None:
    password = cfg.password_file.read_text(encoding="utf-8").strip() if cfg.password_file else ""
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
        if cfg.starttls:
            smtp.starttls()
        if cfg.username:
            smtp.login(cfg.username, password)
        smtp.send_message(build(cfg, subject, body))
