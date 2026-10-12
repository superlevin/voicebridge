"""Endpoint compatibility for the pinned edge-tts 7.2.8 release.

The Edge service migrated from speech.platform.bing.com in October 2026.
See https://github.com/rany2/edge-tts/issues/490 and Readest commit
6ad1e2c6963b8e587aa96401b455e817fc672f8c. Remove this adapter when upgrading
to an edge-tts release with native support for the new endpoint.
"""
import edge_tts.communicate as communicate
from edge_tts.constants import TRUSTED_CLIENT_TOKEN


SPEECH_URL = (
    'wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1'
    f'?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}'
)


def configure_endpoint():
    # communicate imports WSS_URL by value, so patch that binding rather than
    # site-packages on disk. Keep TLS verification and upstream token handling.
    communicate.WSS_URL = SPEECH_URL
