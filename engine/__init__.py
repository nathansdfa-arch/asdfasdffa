"""The trading engine.

The engine is a standalone program (a "service"). It owns all trading logic,
the database and, later, the broker connections and the risk guard. Every
screen (the Windows window, a browser, a phone) is only a client that talks
to the engine through its local API.
"""

# The app's version number. Bump it in CHANGELOG.md too when it changes.
__version__ = "0.3.0"
