VPN_SHORT_SESSION_SECONDS = 120
VPN_MANY_SHORT_RECONNECTS_THRESHOLD = 20
VPN_LONG_SESSION_SECONDS = 8 * 3600
VPN_DENIED_THRESHOLD_PER_IP = 10
SDWAN_PACKET_LOSS_WARN = 2.0
SDWAN_PACKET_LOSS_HIGH = 5.0
SDWAN_LATENCY_WARN_MS = 120
SDWAN_JITTER_WARN_MS = 30
# Il Botnet Detection blocca ogni giorno migliaia di connessioni su un firewall reale (2,8K/giorno nei campioni):
# sotto questa soglia e' protezione che funziona, non un incidente.
BOTNET_BLOCKED_WARN_THRESHOLD = 5000
LICENSE_EXPIRY_WARN_DAYS = 60
