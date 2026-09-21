"""Opt-in LAN preview of the isolated demo; respondent HTTPS guards remain active."""
import ipaddress
import os
from django.core.exceptions import ImproperlyConfigured
from .participation_demo import *  # noqa: F403

try:
    demo_address = ipaddress.IPv4Address(os.environ.get('NEXORA_DEMO_LAN_IP', ''))
except ValueError as exc:
    raise ImproperlyConfigured('NEXORA_DEMO_LAN_IP must be an explicit private IPv4 address.') from exc
if not any(demo_address in ipaddress.ip_network(network) for network in
           ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
    raise ImproperlyConfigured('LAN preview requires an RFC1918 private address.')
DEBUG = False
ALLOWED_HOSTS = [str(demo_address)]
