"""data_ingestion.connectors — one module per external data source."""
from data_ingestion.connectors.ookla import OoklaConnector
from data_ingestion.connectors.ibge import IBGEConnector
from data_ingestion.connectors.anatel import AnatelConnector
from data_ingestion.connectors.opencellid import OpenCelliDConnector
from data_ingestion.connectors.mlab import MLABConnector
from data_ingestion.connectors.cloudflare import CloudflareRadarConnector

__all__ = ["OoklaConnector", "IBGEConnector", "AnatelConnector",
           "OpenCelliDConnector", "MLABConnector", "CloudflareRadarConnector"]
