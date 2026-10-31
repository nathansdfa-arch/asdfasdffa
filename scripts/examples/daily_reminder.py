# Example automation: a reminder before the US stock market opens.
# Automations react to a time or an event. This one runs every weekday at
# 09:25 New York time and only shows a message; it places no orders.

name = "Pre-open reminder"
schedule = "09:25 America/New_York"


def run(event):
    alert("US market opens in 5 minutes. Check the news calendar.")
