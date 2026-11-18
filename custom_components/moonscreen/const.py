"""Constants for the MoonScreen integration."""

from __future__ import annotations

DOMAIN = "moonscreen"
NAME = "MoonScreen"
DEFAULT_ENTITY_NAME = "电脑屏幕"

DEFAULT_HTTPS_PORT = 47984
DEFAULT_HTTP_PORT = 47989
DEFAULT_WEB_PORT = 47990

DEFAULT_DESKTOP_APP_NAME = "Desktop"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 60
DEFAULT_POLL_INTERVAL = 15

MIN_DIMENSION = 640
MAX_DIMENSION = 7680
MIN_FPS = 30
MAX_FPS = 240
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 120

CONF_HOST = "host"
CONF_HTTPS_PORT = "https_port"
CONF_HTTP_PORT = "http_port"
CONF_WEB_PORT = "web_port"
CONF_CLIENT_CERT = "client_cert_pem"
CONF_CLIENT_KEY = "client_key_pem"
CONF_SERVER_CERT = "server_cert_pem"
CONF_CLIENT_UNIQUE_ID = "client_unique_id"
CONF_PAIRING_NAME = "pairing_name"
CONF_DESKTOP_APP_NAME = "desktop_app_name"
CONF_WIDTH = "width"
CONF_HEIGHT = "height"
CONF_FPS = "fps"
CONF_POLL_INTERVAL = "poll_interval"
CONF_WEB_USERNAME = "web_username"
CONF_WEB_PASSWORD = "web_password"
CONF_PROTECT_ACTIVE_STREAM = "protect_active_stream"
CONF_SERVER_UNIQUE_ID = "server_uniqueid"
CONF_SERVER_HOSTNAME = "server_hostname"
CONF_SERVER_VERSION = "server_version"
CONF_PAIRING_PIN = "pin"

PLATFORMS = ["switch"]
