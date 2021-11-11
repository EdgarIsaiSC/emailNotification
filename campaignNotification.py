# -*- coding: utf-8 -*-
import asyncio
import json
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

import smtplib, ssl


import boto3
from botocore.exceptions import ClientError


async def get_secret():
    logging.warning("getting secret from manager")
    secret_name = "emailNotificator"
    region_name = "us-east-1"

    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as error:
        raise error
    else:
        if 'SecretString' in get_secret_value_response:
            secret = json.loads(get_secret_value_response['SecretString'])
            await cache.set("emailPassword", secret.get("emailPassword"))
            await cache.set("sendersEmail", secret.get("sendersEmail"))
        else:
            raise Exception("failed decoding secret")


emails_to_notify = [
    "edgarisaiwr@gmail.com"
]

from aiocache import Cache

cache = Cache(Cache.MEMORY)

CAMPAIGNS_URL = "https://api.citasvacunacion.jalisco.gob.mx/registro/getActiveCampaigns"



def get_campaign_diff(active_campaigns, active_campaigns_from_cache=[]) -> list:
    if not active_campaigns_from_cache:
        active_campaigns_from_cache = []
    all_campaigns_in_cache = {}
    campaign_diff = []
    for campaign in active_campaigns_from_cache:
        all_campaigns_in_cache.update({campaign.get("nombre", "no_name_available"): campaign})

    for campaign in active_campaigns:
        if not all_campaigns_in_cache.get(campaign.get("nombre", "no_name_available")):
            campaign_diff.append(campaign)
    return campaign_diff


def get_active_campaigns() -> dict or list:
    campaigns_requsets = requests.get(CAMPAIGNS_URL)
    campaigns_body = {}
    if campaigns_requsets.status_code == 200:
        campaigns_body = campaigns_requsets.json()
    return campaigns_body


async def fetch_campaigns_to_notify() -> dict:
    active_campaigns_from_cache = await cache.get("campaigns")
    active_campaigns = get_active_campaigns()
    new_or_modified_campaigns = get_campaign_diff(active_campaigns, active_campaigns_from_cache)
    await cache.set("campaigns", active_campaigns)
    return new_or_modified_campaigns


async def send_email_notification(campaigns_to_notify):
    senders_email = await cache.get("sendersEmail")
    password = await cache.get("emailPassword")
    message_body = ""
    for campaign in campaigns_to_notify:
        message_body += f"nombre: {campaign.get('nombre', 'not available')}\n"
        message_body += f"descripcion: {campaign.get('descripcion', 'not available')}\n"
        message_body += f"fecha de inicio: {campaign.get('fecha_inicio', 'not available')}\n"
        message_body += f"fecha de fin: {campaign.get('fecha_fin', 'not available')}\n"
        message_body += "-----------------------------------------------------------\n"
    message_body += "https://vacunacion.jalisco.gob.mx"
    message_body = MIMEText(message_body, "plain")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.command_encoding
        server.login(senders_email, password)
        for email in emails_to_notify:
            message = MIMEMultipart("alternative")
            message["Subject"] = "Notification"
            message["From"] = senders_email
            message["To"] = email
            message.attach(message_body)
            server.sendmail(
                senders_email, email, message.as_string()
            )
            logging.warning("email sent")


async def process_campaign_notifications():
    while True:
        if not await cache.get("emailPassword"):
            await get_secret()
        campaigns_to_notify = await fetch_campaigns_to_notify()
        if campaigns_to_notify:
            await send_email_notification(campaigns_to_notify)
        await asyncio.sleep(60)


loop = asyncio.get_event_loop()
loop.run_until_complete(cache.delete("campaigns"))

loop.run_until_complete(process_campaign_notifications())
