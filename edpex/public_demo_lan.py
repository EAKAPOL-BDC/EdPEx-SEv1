"""Explicit synthetic-only LAN respondent preview; never a production setting."""
import ipaddress
import os
from .public_demo import *  # noqa: F403

try:
    preview_ip = ipaddress.IPv4Address(os.environ['NEXORA_DEMO_LAN_IP'])
    preview_network = ipaddress.IPv4Network(os.environ['NEXORA_DEMO_LAN_NETWORK'])
except (KeyError, ValueError) as exc:
    raise ImproperlyConfigured('Explicit LAN IP and network required.') from exc
if (preview_ip not in preview_network or not any(preview_network.subnet_of(ipaddress.ip_network(n))
        for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))):
    raise ImproperlyConfigured('Preview must bind to its private LAN network.')
DEBUG = False
ALLOWED_HOSTS = [str(preview_ip)]
NEXORA_SYNTHETIC_LAN_NETWORK = str(preview_network)
NEXORA_SYNTHETIC_LAN_HOST = str(preview_ip)
MIDDLEWARE = ['apps.participation.lan_preview.PublicPreviewOnlyMiddleware', *MIDDLEWARE]

